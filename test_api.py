#!/usr/bin/env python3
"""
Simple test script for the Chart Data API
"""
import requests
import json

# API base URL
BASE_URL = "http://localhost:5003"

def test_health():
    """Test the health endpoint"""
    print("🔍 Testing health endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"✅ Health check: {response.status_code}")
        print(f"   Response: {response.json()}")
    except Exception as e:
        print(f"❌ Health check failed: {e}")

def test_symbols():
    """Test the symbols endpoint"""
    print("\n🔍 Testing symbols endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/symbols")
        print(f"✅ Symbols: {response.status_code}")
        data = response.json()
        print(f"   Available categories: {list(data.keys())}")
    except Exception as e:
        print(f"❌ Symbols test failed: {e}")

def test_chart_data(symbol="AAPL", timeframes=None):
    """Test the multi-timeframe chart data endpoint"""
    if timeframes is None:
        timeframes = ["1d", "4h", "1h", "15m"]
    
    print(f"\n🔍 Testing multi-timeframe analysis for {symbol}...")
    try:
        payload = {
            "symbol": symbol,
            "timeframes": timeframes,
            "analysis_period": "3mo"
        }
        response = requests.post(
            f"{BASE_URL}/chart-data",
            headers={"Content-Type": "application/json"},
            json=payload
        )
        print(f"✅ Multi-timeframe analysis: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"   Company: {data.get('company_name')}")
            print(f"   Current price: ${data.get('metadata', {}).get('current_price')}")
            
            # Show analysis for each timeframe
            mtf_analysis = data.get('multi_timeframe_analysis', {})
            
            for tf in timeframes:
                tf_data = mtf_analysis.get(tf, {})
                if 'error' in tf_data:
                    print(f"   ❌ {tf.upper()}: {tf_data['error']}")
                    continue
                    
                print(f"\n   📊 {tf.upper()} Timeframe ({tf_data.get('context', 'N/A')}):")
                print(f"      Data points: {tf_data.get('data_points', 'N/A')}")
                
                # 20 EMA
                ema_20 = tf_data.get('ema_20', {})
                if ema_20:
                    trend_emoji = "🟢" if ema_20.get('trend') == 'bullish' else "🔴" if ema_20.get('trend') == 'bearish' else "🟡"
                    position_emoji = "⬆️" if ema_20.get('price_vs_ema') == 'above' else "⬇️"
                    print(f"      20 EMA: ${ema_20.get('current', 'N/A')} {trend_emoji} {position_emoji}")
                
                # Smart Money Concepts
                smc = tf_data.get('smart_money_concepts', {})
                
                # Order Blocks
                order_blocks = smc.get('order_blocks', [])
                if order_blocks:
                    latest_ob = order_blocks[-1]
                    ob_emoji = "🟢" if latest_ob['type'] == 'bullish_ob' else "🔴"
                    print(f"      Latest Order Block: {latest_ob['type'].replace('_', ' ').title()} {ob_emoji}")
                
                # Fair Value Gaps
                fvgs = smc.get('fair_value_gaps', [])
                if fvgs:
                    print(f"      Fair Value Gaps: {len(fvgs)} active")
                
                # Premium/Discount (Daily and 4H only)
                premium_discount = smc.get('premium_discount', {})
                if premium_discount:
                    bias = premium_discount.get('current_bias', '')
                    bias_emoji = "🟢" if 'discount' in bias else "🔴" if 'premium' in bias else "🟡"
                    print(f"      Market Bias: {bias.replace('_', ' ').title()} {bias_emoji}")
                
                # Trading Signals
                signals = tf_data.get('trading_signals', {})
                overall_bias = signals.get('overall_bias', 'neutral')
                bias_emoji = "🟢" if overall_bias == 'bullish' else "🔴" if overall_bias == 'bearish' else "🟡"
                print(f"      Overall Bias: {overall_bias.title()} {bias_emoji}")
                
                entry_signals = signals.get('entry_signals', [])
                if entry_signals:
                    print(f"      Entry Signals: {len(entry_signals)} active")
                    for signal in entry_signals[:2]:  # Show first 2
                        print(f"        • {signal}")
                
                confluence_factors = signals.get('confluence_factors', [])
                if confluence_factors:
                    print(f"      Confluence: {len(confluence_factors)} factors")
        else:
            print(f"   Error: {response.json()}")
    except Exception as e:
        print(f"❌ Multi-timeframe analysis test failed: {e}")

if __name__ == "__main__":
    print("🧪 Testing Smart Money Concepts Multi-Timeframe API\n")
    
    test_health()
    test_symbols()
    test_chart_data("AAPL", ["1d", "4h"])  # Test fewer timeframes for faster response
    test_chart_data("TSLA", ["1d", "1h"])
    test_chart_data("BTC-USD", ["4h", "15m"])
    
    print("\n🎉 Testing complete!")
