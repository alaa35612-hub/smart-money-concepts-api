import os
from flask import Flask, request, jsonify
import yfinance as yf
import requests
import json
from datetime import datetime, timedelta
import logging
import pandas as pd
import numpy as np

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

def calculate_volume_profile(df, num_levels=20):
    """
    Calculate Volume Profile (volume distribution by price levels)
    Returns volume traded at each price level
    """
    try:
        if df.empty or 'High' not in df.columns or 'Low' not in df.columns or 'Volume' not in df.columns:
            return []
        
        # Calculate price range
        price_min = df['Low'].min()
        price_max = df['High'].max()
        
        # Create price levels
        price_levels = np.linspace(price_min, price_max, num_levels + 1)
        volume_profile = []
        
        for i in range(len(price_levels) - 1):
            level_low = price_levels[i]
            level_high = price_levels[i + 1]
            level_mid = (level_low + level_high) / 2
            
            # Calculate volume for this price level
            level_volume = 0
            
            for idx, row in df.iterrows():
                candle_low = row['Low']
                candle_high = row['High']
                candle_volume = row['Volume']
                
                # Calculate overlap between candle range and price level
                overlap_low = max(level_low, candle_low)
                overlap_high = min(level_high, candle_high)
                
                if overlap_high > overlap_low:
                    candle_range = candle_high - candle_low
                    if candle_range > 0:
                        overlap_fraction = (overlap_high - overlap_low) / candle_range
                        level_volume += candle_volume * overlap_fraction
            
            volume_profile.append({
                "price_level": round(level_mid, 2),
                "price_low": round(level_low, 2),
                "price_high": round(level_high, 2),
                "volume": int(level_volume)
            })
        
        # Sort by volume descending and mark POC
        volume_profile.sort(key=lambda x: x['volume'], reverse=True)
        if volume_profile:
            volume_profile[0]['is_poc'] = True
        volume_profile.sort(key=lambda x: x['price_level'])
        
        return volume_profile
        
    except Exception as e:
        logging.error(f"Error calculating volume profile: {str(e)}")
        return []

def calculate_ema(prices, period):
    """Calculate Exponential Moving Average"""
    if len(prices) < period:
        return pd.Series(dtype=float)
    
    alpha = 2 / (period + 1)
    ema = prices.ewm(alpha=alpha, adjust=False).mean()
    return ema

def detect_swing_points(df, window=5):
    """Detect swing highs and lows"""
    highs = []
    lows = []
    
    for i in range(window, len(df) - window):
        # Check for swing high
        is_high = all(df['High'].iloc[i] >= df['High'].iloc[j] for j in range(i - window, i + window + 1) if j != i)
        if is_high:
            highs.append({'index': i, 'price': df['High'].iloc[i], 'timestamp': df.index[i].strftime('%Y-%m-%d %H:%M:%S'), 'type': 'swing_high'})
        
        # Check for swing low
        is_low = all(df['Low'].iloc[i] <= df['Low'].iloc[j] for j in range(i - window, i + window + 1) if j != i)
        if is_low:
            lows.append({'index': i, 'price': df['Low'].iloc[i], 'timestamp': df.index[i].strftime('%Y-%m-%d %H:%M:%S'), 'type': 'swing_low'})
    
    return highs, lows

def detect_structure_levels(df):
    """Detect HH, LL, iBOS, ChoCH"""
    highs, lows = detect_swing_points(df)
    
    structure = {'higher_highs': [], 'lower_lows': [], 'internal_bos': [], 'change_of_character': []}
    
    # Higher Highs
    for i in range(1, len(highs)):
        if highs[i]['price'] > highs[i-1]['price']:
            structure['higher_highs'].append(highs[i])
    
    # Lower Lows  
    for i in range(1, len(lows)):
        if lows[i]['price'] < lows[i-1]['price']:
            structure['lower_lows'].append(lows[i])
    
    return structure

def detect_order_blocks(df, window=20):
    """Detect Order Blocks (institutional candles before strong moves)"""
    order_blocks = []
    
    for i in range(window, len(df) - 1):
        current = df.iloc[i]
        next_candle = df.iloc[i + 1]
        
        # Bullish Order Block
        if (current['Close'] < current['Open'] and next_candle['Close'] > next_candle['Open'] and 
            next_candle['Close'] > current['High']):
            order_blocks.append({
                'type': 'bullish_ob', 'high': current['High'], 'low': current['Low'],
                'timestamp': current.name.strftime('%Y-%m-%d %H:%M:%S'), 'index': i
            })
        
        # Bearish Order Block
        elif (current['Close'] > current['Open'] and next_candle['Close'] < next_candle['Open'] and
              next_candle['Close'] < current['Low']):
            order_blocks.append({
                'type': 'bearish_ob', 'high': current['High'], 'low': current['Low'],
                'timestamp': current.name.strftime('%Y-%m-%d %H:%M:%S'), 'index': i
            })
    
    return order_blocks[-10:]

def detect_fair_value_gaps(df):
    """Detect Fair Value Gaps (FVGs)"""
    fvgs = []
    
    for i in range(1, len(df) - 1):
        prev, current, next_candle = df.iloc[i-1], df.iloc[i], df.iloc[i+1]
        
        # Bullish FVG
        if prev['Low'] > next_candle['High']:
            fvgs.append({
                'type': 'bullish_fvg', 'high': prev['Low'], 'low': next_candle['High'],
                'timestamp': current.name.strftime('%Y-%m-%d %H:%M:%S'), 'index': i
            })
        
        # Bearish FVG  
        elif prev['High'] < next_candle['Low']:
            fvgs.append({
                'type': 'bearish_fvg', 'high': next_candle['Low'], 'low': prev['High'],
                'timestamp': current.name.strftime('%Y-%m-%d %H:%M:%S'), 'index': i
            })
    
    return fvgs[-20:]

def calculate_premium_discount_zones(df, window=50):
    """Calculate Premium/Discount zones based on swing range"""
    if len(df) < window:
        return None
    
    recent_data = df.tail(window)
    swing_high = recent_data['High'].max()
    swing_low = recent_data['Low'].min()
    range_size = swing_high - swing_low
    
    levels = {
        'swing_high': swing_high,
        'premium_zone': swing_high - (range_size * 0.382),
        'equilibrium': swing_low + (range_size * 0.5),
        'discount_zone': swing_low + (range_size * 0.382),
        'swing_low': swing_low
    }
    
    current_price = df['Close'].iloc[-1]
    
    if current_price > levels['equilibrium']:
        bias = 'premium' if current_price > levels['premium_zone'] else 'neutral_premium'
    else:
        bias = 'discount' if current_price < levels['discount_zone'] else 'neutral_discount'
    
    return {'levels': levels, 'current_bias': bias, 'current_price': current_price}

def detect_liquidity_zones(df):
    """Detect equal highs/lows (liquidity zones)"""
    highs, lows = detect_swing_points(df)
    liquidity_zones = {'equal_highs': [], 'equal_lows': []}
    tolerance = 0.005
    
    # Equal highs
    processed_highs = set()
    for i, high in enumerate(highs):
        if i in processed_highs:
            continue
        equal_group = [high]
        for j, other_high in enumerate(highs[i+1:], i+1):
            price_diff = abs(high['price'] - other_high['price']) / high['price']
            if price_diff <= tolerance:
                equal_group.append(other_high)
                processed_highs.add(j)
        
        if len(equal_group) >= 2:
            liquidity_zones['equal_highs'].append({
                'price_level': sum(h['price'] for h in equal_group) / len(equal_group),
                'count': len(equal_group),
                'timestamps': [h['timestamp'] for h in equal_group]
            })
    
    # Equal lows
    processed_lows = set()
    for i, low in enumerate(lows):
        if i in processed_lows:
            continue
        equal_group = [low]
        for j, other_low in enumerate(lows[i+1:], i+1):
            price_diff = abs(low['price'] - other_low['price']) / low['price']
            if price_diff <= tolerance:
                equal_group.append(other_low)
                processed_lows.add(j)
        
        if len(equal_group) >= 2:
            liquidity_zones['equal_lows'].append({
                'price_level': sum(l['price'] for l in equal_group) / len(equal_group),
                'count': len(equal_group),
                'timestamps': [l['timestamp'] for l in equal_group]
            })
    
    return liquidity_zones

def generate_trading_signals(analysis, timeframe):
    """Generate trading signals based on SMC analysis"""
    signals = {'overall_bias': 'neutral', 'entry_signals': [], 'risk_levels': [], 'confluence_factors': []}
    
    try:
        # EMA trend bias
        ema_data = analysis.get('ema_20', {})
        if ema_data:
            if ema_data.get('trend') == 'bullish' and ema_data.get('price_vs_ema') == 'above':
                signals['confluence_factors'].append('Price above rising 20 EMA (bullish)')
                signals['overall_bias'] = 'bullish'
            elif ema_data.get('trend') == 'bearish' and ema_data.get('price_vs_ema') == 'below':
                signals['confluence_factors'].append('Price below falling 20 EMA (bearish)')
                signals['overall_bias'] = 'bearish'
        
        # Premium/Discount bias
        smc = analysis.get('smart_money_concepts', {})
        premium_discount = smc.get('premium_discount', {})
        if premium_discount:
            bias = premium_discount.get('current_bias', '')
            if 'discount' in bias:
                signals['confluence_factors'].append('Price in discount zone (bullish bias)')
                signals['entry_signals'].append('Look for bullish setups in discount zone')
            elif 'premium' in bias:
                signals['confluence_factors'].append('Price in premium zone (bearish bias)')
                signals['entry_signals'].append('Look for bearish setups in premium zone')
        
        # Order Block signals
        order_blocks = smc.get('order_blocks', [])
        recent_obs = [ob for ob in order_blocks if ob.get('index', 0) >= 80]
        if recent_obs:
            latest_ob = recent_obs[-1]
            if latest_ob['type'] == 'bullish_ob':
                signals['entry_signals'].append(f"Bullish Order Block at {latest_ob['low']:.2f}")
                signals['risk_levels'].append(f"Stop below {latest_ob['low']:.2f}")
            else:
                signals['entry_signals'].append(f"Bearish Order Block at {latest_ob['high']:.2f}")
                signals['risk_levels'].append(f"Stop above {latest_ob['high']:.2f}")
        
        # FVG signals
        fvgs = smc.get('fair_value_gaps', [])
        for fvg in fvgs[-3:]:
            if fvg['type'] == 'bullish_fvg':
                signals['entry_signals'].append(f"Bullish FVG: {fvg['low']:.2f} - {fvg['high']:.2f}")
            else:
                signals['entry_signals'].append(f"Bearish FVG: {fvg['low']:.2f} - {fvg['high']:.2f}")
        
        # Liquidity signals
        liquidity = smc.get('liquidity_zones', {})
        current_price = analysis['current_price']
        
        for eq_high in liquidity.get('equal_highs', [])[-3:]:
            if abs(current_price - eq_high['price_level']) / current_price < 0.02:
                signals['entry_signals'].append(f"Near Equal Highs liquidity at {eq_high['price_level']:.2f}")
        
        for eq_low in liquidity.get('equal_lows', [])[-3:]:
            if abs(current_price - eq_low['price_level']) / current_price < 0.02:
                signals['entry_signals'].append(f"Near Equal Lows liquidity at {eq_low['price_level']:.2f}")
        
        return signals
        
    except Exception as e:
        logging.error(f"Error generating trading signals: {str(e)}")
        return signals

def perform_comprehensive_analysis(df, timeframe, symbol):
    """Perform comprehensive multi-timeframe analysis with SMC"""
    try:
        analysis = {
            'timeframe': timeframe,
            'data_points': len(df),
            'current_price': round(float(df['Close'].iloc[-1]), 2),
            'price_change_24h': round(float(df['Close'].iloc[-1] - df['Close'].iloc[-2]), 2) if len(df) > 1 else 0,
            'chart_data': []
        }
        
        # Convert chart data (last 100 candles)
        for index, row in df.tail(100).iterrows():
            analysis['chart_data'].append({
                "date": index.strftime('%Y-%m-%d %H:%M:%S'),
                "timestamp": int(index.timestamp()),
                "open": round(float(row['Open']), 2),
                "high": round(float(row['High']), 2),
                "low": round(float(row['Low']), 2),
                "close": round(float(row['Close']), 2),
                "volume": int(row['Volume']) if row['Volume'] else 0
            })
        
        # 20 EMA for dynamic support/resistance
        if len(df) >= 20:
            ema_20 = calculate_ema(df['Close'], 20)
            if not ema_20.empty:
                analysis['ema_20'] = {
                    'current': round(float(ema_20.iloc[-1]), 2),
                    'previous': round(float(ema_20.iloc[-2]), 2) if len(ema_20) > 1 else None,
                    'trend': 'bullish' if len(ema_20) > 1 and ema_20.iloc[-1] > ema_20.iloc[-2] else 'bearish' if len(ema_20) > 1 else 'neutral',
                    'price_vs_ema': 'above' if df['Close'].iloc[-1] > ema_20.iloc[-1] else 'below'
                }
        
        # Volume Profile
        analysis['volume_profile'] = calculate_volume_profile(df)
        
        # Smart Money Concepts
        analysis['smart_money_concepts'] = {
            'structure_levels': detect_structure_levels(df),
            'order_blocks': detect_order_blocks(df),
            'fair_value_gaps': detect_fair_value_gaps(df),
            'liquidity_zones': detect_liquidity_zones(df)
        }
        
        # Premium/Discount Zones (for Daily and 4H)
        if timeframe in ['1d', '4h']:
            premium_discount = calculate_premium_discount_zones(df)
            if premium_discount:
                analysis['smart_money_concepts']['premium_discount'] = premium_discount
        
        # Timeframe-specific context
        contexts = {
            '1d': ('Trend direction and overall market structure', 'Identify major support/resistance and overall bias'),
            '4h': ('Medium-term structure and reaction zones', 'Refine entries based on daily bias'),
            '1h': ('Entry planning and tighter structure', 'Fine-tune entry levels and stop placement'),
            '15m': ('Entry timing and confirmation', 'Precise entry execution and quick confirmations')
        }
        
        if timeframe in contexts:
            analysis['context'] = contexts[timeframe][0]
            analysis['purpose'] = contexts[timeframe][1]
        
        # Trading signals based on SMC
        analysis['trading_signals'] = generate_trading_signals(analysis, timeframe)
        
        return analysis
        
    except Exception as e:
        logging.error(f"Error in comprehensive analysis for {timeframe}: {str(e)}")
        return {'error': f"Analysis failed for {timeframe}: {str(e)}"}

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/chart-data', methods=['POST'])
def get_chart_data():
    """Multi-timeframe analysis with Smart Money Concepts"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
        
        symbol = data.get('symbol', '').upper()
        timeframes = data.get('timeframes', ['1d', '4h', '1h', '15m'])
        analysis_period = data.get('analysis_period', '3mo')
        callback_url = data.get('callback_url')  # Optional webhook URL
        
        if not symbol:
            return jsonify({"error": "Symbol is required"}), 400
        
        logging.info(f"Multi-timeframe analysis for {symbol} on timeframes: {timeframes}")
        
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # Multi-timeframe analysis
        mtf_analysis = {}
        
        for tf in timeframes:
            logging.info(f"Analyzing {symbol} on {tf} timeframe")
            hist_data = ticker.history(period=analysis_period, interval=tf)
            
            if hist_data.empty:
                mtf_analysis[tf] = {"error": f"No data available for {tf} timeframe"}
                continue
            
            analysis = perform_comprehensive_analysis(hist_data, tf, symbol)
            mtf_analysis[tf] = analysis
        
        response_data = {
            "symbol": symbol,
            "company_name": info.get('longName', symbol),
            "currency": info.get('currency', 'USD'),
            "analysis_period": analysis_period,
            "timeframes_analyzed": timeframes,
            "multi_timeframe_analysis": mtf_analysis,
            "metadata": {
                "current_price": mtf_analysis.get('1d', {}).get('current_price'),
                "market_cap": info.get('marketCap'),
                "pe_ratio": info.get('trailingPE'),
                "52_week_high": info.get('fiftyTwoWeekHigh'),
                "52_week_low": info.get('fiftyTwoWeekLow')
            },
            "fetched_at": datetime.now().isoformat()
        }
        
        # Send to callback URL if provided (webhook functionality)
        if callback_url:
            try:
                logging.info(f"Sending webhook to {callback_url}")
                webhook_response = requests.post(
                    callback_url,
                    json=response_data,
                    headers={'Content-Type': 'application/json'},
                    timeout=30
                )
                logging.info(f"Webhook sent, status: {webhook_response.status_code}")
                
                return jsonify({
                    "message": "Analysis completed and sent to webhook",
                    "webhook_status": webhook_response.status_code,
                    "analysis_summary": {
                        "symbol": symbol,
                        "timeframes": timeframes,
                        "data_points": sum(tf_data.get('data_points', 0) for tf_data in mtf_analysis.values() if isinstance(tf_data, dict) and 'data_points' in tf_data)
                    }
                })
                
            except requests.exceptions.RequestException as e:
                logging.error(f"Webhook failed: {str(e)}")
                # Return the data even if webhook fails
                return jsonify({
                    "message": "Analysis completed but webhook failed",
                    "webhook_error": str(e),
                    "data": response_data
                }), 207  # Multi-status
        
        # Return data directly if no callback URL
        return jsonify(response_data)
        
    except Exception as e:
        logging.error(f"Error processing request: {str(e)}")
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/symbols', methods=['GET'])
def get_popular_symbols():
    """Return list of popular stock and commodity symbols"""
    symbols = {
        "stocks": {
            "tech": ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "META", "NVDA"],
            "finance": ["JPM", "BAC", "WFC", "GS", "MS"],
            "indices": ["^GSPC", "^DJI", "^IXIC", "^RUT"]
        },
        "commodities": {
            "metals": ["GC=F", "SI=F", "PL=F", "PA=F"],
            "energy": ["CL=F", "NG=F", "BZ=F"],
            "agriculture": ["ZC=F", "ZS=F", "ZW=F"]
        },
        "crypto": ["BTC-USD", "ETH-USD", "BNB-USD", "XRP-USD", "ADA-USD"],
        "forex": ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X"]
    }
    return jsonify(symbols)

if __name__ == '__main__':
    print("🚀 Smart Money Concepts Multi-Timeframe Analysis Service starting...")
    print("📊 Available endpoints:")
    print("   GET  /health - Health check")
    print("   POST /chart-data - Multi-timeframe SMC analysis")
    print("   GET  /symbols - List popular symbols")
    print("\n🎯 Smart Money Concepts included:")
    print("   • Volume Profile with POC")
    print("   • 20 EMA dynamic support/resistance")
    print("   • Structure Levels (HH, LL, iBOS, ChoCH)")
    print("   • Order Blocks (institutional levels)")
    print("   • Fair Value Gaps (FVGs)")
    print("   • Liquidity Zones (equal highs/lows)")
    print("   • Premium/Discount analysis (Daily/4H)")
    print("   • Multi-timeframe confluence signals")
    
    # Use environment variable for port (for deployment) or default to 5003 for local
    port = int(os.environ.get('PORT', 5003))
    debug = os.environ.get('FLASK_ENV') != 'production'
    
    print(f"\n💡 Starting on port {port} (debug: {debug})")
    app.run(host='0.0.0.0', port=port, debug=debug)
