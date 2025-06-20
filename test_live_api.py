#!/usr/bin/env python3
"""
Test script for live/deployed Smart Money Concepts API
"""
import requests
import json
import sys

def test_live_api(base_url):
    """Test the live API endpoints"""
    
    print(f"🧪 Testing Live Smart Money Concepts API at: {base_url}\n")
    
    # Remove trailing slash
    base_url = base_url.rstrip('/')
    
    def test_health():
        """Test the health endpoint"""
        print("🔍 Testing health endpoint...")
        try:
            response = requests.get(f"{base_url}/health", timeout=30)
            print(f"✅ Health check: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"   Status: {data.get('status')}")
                print(f"   Timestamp: {data.get('timestamp')}")
            else:
                print(f"   Error: {response.text}")
        except Exception as e:
            print(f"❌ Health check failed: {e}")

    def test_symbols():
        """Test the symbols endpoint"""
        print("\n🔍 Testing symbols endpoint...")
        try:
            response = requests.get(f"{base_url}/symbols", timeout=30)
            print(f"✅ Symbols: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                categories = list(data.keys())
                print(f"   Available categories: {categories}")
                total_symbols = sum(len(v) if isinstance(v, list) else sum(len(subv) for subv in v.values()) for v in data.values())
                print(f"   Total symbols available: {total_symbols}")
            else:
                print(f"   Error: {response.text}")
        except Exception as e:
            print(f"❌ Symbols test failed: {e}")

    def test_chart_data(symbol="AAPL", timeframes=["1d"]):
        """Test the chart data endpoint"""
        print(f"\n🔍 Testing multi-timeframe analysis for {symbol}...")
        try:
            payload = {
                "symbol": symbol,
                "timeframes": timeframes,
                "analysis_period": "1mo"  # Shorter period for faster testing
            }
            response = requests.post(
                f"{base_url}/chart-data",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=60  # Longer timeout for data fetching
            )
            print(f"✅ Multi-timeframe analysis: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"   Company: {data.get('company_name')}")
                print(f"   Current price: ${data.get('metadata', {}).get('current_price')}")
                
                mtf_analysis = data.get('multi_timeframe_analysis', {})
                for tf in timeframes:
                    tf_data = mtf_analysis.get(tf, {})
                    if 'error' in tf_data:
                        print(f"   ❌ {tf.upper()}: {tf_data['error']}")
                        continue
                    
                    print(f"\n   📊 {tf.upper()} Analysis:")
                    print(f"      Data points: {tf_data.get('data_points')}")
                    
                    # EMA
                    ema_20 = tf_data.get('ema_20', {})
                    if ema_20:
                        trend_emoji = "🟢" if ema_20.get('trend') == 'bullish' else "🔴" if ema_20.get('trend') == 'bearish' else "🟡"
                        print(f"      20 EMA: ${ema_20.get('current')} {trend_emoji}")
                    
                    # Trading signals
                    signals = tf_data.get('trading_signals', {})
                    bias = signals.get('overall_bias', 'neutral')
                    bias_emoji = "🟢" if bias == 'bullish' else "🔴" if bias == 'bearish' else "🟡"
                    print(f"      Overall Bias: {bias.title()} {bias_emoji}")
                    
                    entry_signals = signals.get('entry_signals', [])
                    if entry_signals:
                        print(f"      Entry Signals: {len(entry_signals)} active")
                        
                    # Volume profile
                    volume_profile = tf_data.get('volume_profile', [])
                    if volume_profile:
                        poc_level = next((level for level in volume_profile if level.get('is_poc')), None)
                        if poc_level:
                            print(f"      POC: ${poc_level['price_level']}")
                            
            else:
                print(f"   Error: {response.text}")
                
        except Exception as e:
            print(f"❌ Chart data test failed: {e}")

    # Run all tests
    test_health()
    test_symbols()
    test_chart_data("AAPL", ["1d"])
    test_chart_data("BTC-USD", ["4h"])
    
    print("\n🎉 Live API testing complete!")
    print(f"\n🌐 Your API is live at: {base_url}")
    print("📡 Ready for webhook requests 24/7!")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python test_live_api.py <your-live-url>")
        print("Example: python test_live_api.py https://smc-api-production.railway.app")
        sys.exit(1)
    
    live_url = sys.argv[1]
    test_live_api(live_url)
