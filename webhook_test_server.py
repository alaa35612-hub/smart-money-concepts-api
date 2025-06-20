#!/usr/bin/env python3
"""
Webhook test server to receive data from your live Smart Money Concepts API
Run this to test webhook functionality
"""

from flask import Flask, request, jsonify
import json
from datetime import datetime

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def receive_webhook():
    """Receive webhook data from your live API"""
    try:
        data = request.get_json()
        
        print(f"\n🔔 Webhook received at {datetime.now().isoformat()}")
        print("=" * 50)
        
        if data:
            symbol = data.get('symbol', 'Unknown')
            company = data.get('company_name', 'Unknown Company')
            current_price = data.get('metadata', {}).get('current_price', 'N/A')
            
            print(f"📊 Symbol: {symbol}")
            print(f"🏢 Company: {company}")
            print(f"💰 Current Price: ${current_price}")
            
            # Show analysis for each timeframe
            mtf_analysis = data.get('multi_timeframe_analysis', {})
            for timeframe, analysis in mtf_analysis.items():
                if 'error' in analysis:
                    continue
                    
                print(f"\n📈 {timeframe.upper()} Analysis:")
                
                # EMA trend
                ema_20 = analysis.get('ema_20', {})
                if ema_20:
                    trend = ema_20.get('trend', 'neutral')
                    ema_price = ema_20.get('current', 'N/A')
                    print(f"   20 EMA: ${ema_price} (trend: {trend})")
                
                # Trading signals
                signals = analysis.get('trading_signals', {})
                bias = signals.get('overall_bias', 'neutral')
                entry_signals = signals.get('entry_signals', [])
                
                print(f"   Overall Bias: {bias}")
                if entry_signals:
                    print(f"   Entry Signals: {len(entry_signals)} active")
                    for signal in entry_signals[:2]:  # Show first 2
                        print(f"     • {signal}")
            
            print("=" * 50)
            print("✅ Webhook processed successfully")
            
        else:
            print("❌ No data received in webhook")
            
        return jsonify({"status": "received", "timestamp": datetime.now().isoformat()})
        
    except Exception as e:
        print(f"❌ Error processing webhook: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check for webhook server"""
    return jsonify({"status": "healthy", "message": "Webhook server running"})

if __name__ == '__main__':
    print("🎣 Starting Webhook Test Server...")
    print("📡 Listening for webhooks at: http://localhost:3000/webhook")
    print("🔧 Health check: http://localhost:3000/health")
    print("\n💡 To test with your live API, send requests like:")
    print("curl -X POST https://your-live-api.railway.app/chart-data \\")
    print("  -H 'Content-Type: application/json' \\")
    print("  -d '{")
    print('    "symbol": "AAPL",')
    print('    "timeframes": ["1d"],')
    print('    "callback_url": "http://localhost:3000/webhook"')
    print("  }'")
    print("\n🛑 Press Ctrl+C to stop")
    
    app.run(host='0.0.0.0', port=3000, debug=True)
