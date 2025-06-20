# Smart Money Concepts API 🚀📊

Professional multi-timeframe Smart Money Concepts analysis API with 24/7 availability.

## 🌟 Features

- **Multi-timeframe Analysis**: 1D, 4H, 1H, 15M
- **Smart Money Concepts**: Order Blocks, FVGs, Liquidity Zones, Structure Levels
- **Volume Profile**: POC analysis and volume distribution
- **20 EMA**: Dynamic support/resistance
- **Premium/Discount Analysis**: Market bias determination
- **Trading Signals**: Entry points with confluence factors

## 🚀 Quick Deploy (24/7 Live)

### Railway (Recommended - Free & Easy)

1. **Fork/Clone this repo to GitHub**
2. **Go to [railway.app](https://railway.app)**
3. **Connect GitHub and deploy this repository**
4. **Get your live URL**: `https://your-app.railway.app`

### Alternative Deployment Options

- **Render**: [render.com](https://render.com) - Free tier available
- **Heroku**: [heroku.com](https://heroku.com) - Easy but paid
- **DigitalOcean App Platform**: [digitalocean.com](https://www.digitalocean.com/products/app-platform)

## 💻 Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python app.py
```

## 📡 API Usage

### Endpoints

- `GET /health` - Health check
- `GET /symbols` - Available symbols
- `POST /chart-data` - Multi-timeframe analysis

### Example Request

```bash
curl -X POST https://your-live-url.railway.app/chart-data \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "AAPL",
    "timeframes": ["1d", "4h", "1h"],
    "analysis_period": "3mo"
  }'
```

### Example Response

```json
{
  "symbol": "AAPL",
  "company_name": "Apple Inc.",
  "multi_timeframe_analysis": {
    "1d": {
      "timeframe": "1d",
      "current_price": 201.0,
      "ema_20": {
        "current": 200.4,
        "trend": "bullish",
        "price_vs_ema": "above"
      },
      "smart_money_concepts": {
        "order_blocks": [...],
        "fair_value_gaps": [...],
        "liquidity_zones": {...},
        "premium_discount": {
          "current_bias": "premium",
          "levels": {...}
        }
      },
      "trading_signals": {
        "overall_bias": "bullish",
        "entry_signals": [...],
        "confluence_factors": [...]
      }
    }
  }
}
```

## 🎯 Use Cases

**Day Trading**: `{"timeframes": ["1h", "15m"]}`
**Swing Trading**: `{"timeframes": ["1d", "4h"]}`
**Scalping**: `{"timeframes": ["15m"], "analysis_period": "1mo"}`

## 🔧 Integration

Perfect for:
- n8n workflows
- Trading bots
- Webhook notifications
- Automated signal generation
- Portfolio analysis

## 🛡️ Production Ready

- Health checks
- Error handling
- Logging
- Rate limiting ready
- Environment configuration