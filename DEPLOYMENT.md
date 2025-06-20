# 24/7 Deployment Guide 🚀

## Railway Deployment (Recommended)

Railway is the easiest way to get your API live 24/7 with zero configuration.

### Step 1: Push to GitHub

```bash
cd /Users/joaocosta/chart-webhook-service

# Initialize git repository
git init
git add .
git commit -m "Initial commit: Smart Money Concepts API"

# Create GitHub repository and push
git remote add origin https://github.com/yourusername/smc-api.git
git branch -M main
git push -u origin main
```

### Step 2: Deploy on Railway

1. Go to [railway.app](https://railway.app)
2. Sign up with GitHub
3. Click "New Project"
4. Select "Deploy from GitHub repo"
5. Choose your `smc-api` repository
6. Railway auto-deploys!

### Step 3: Get Your Live URL

Railway provides a URL like:
- `https://smc-api-production.railway.app`
- Your endpoints will be:
  - `https://smc-api-production.railway.app/health`
  - `https://smc-api-production.railway.app/chart-data`

### Step 4: Test Your Live API

```bash
curl -X POST https://smc-api-production.railway.app/chart-data \
  -H "Content-Type: application/json" \
  -d '{"symbol": "AAPL", "timeframes": ["1d", "4h"]}'
```

---

## Alternative: Render Deployment

### Step 1: Push to GitHub (same as above)

### Step 2: Deploy on Render

1. Go to [render.com](https://render.com)
2. Sign up with GitHub
3. Click "New Web Service"
4. Connect your GitHub repository
5. Configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn --bind 0.0.0.0:$PORT app:app`
   - **Environment**: Python 3

---

## Alternative: DigitalOcean App Platform

### Step 1: Push to GitHub (same as above)

### Step 2: Deploy on DigitalOcean

1. Go to [digitalocean.com/products/app-platform](https://www.digitalocean.com/products/app-platform)
2. Create account
3. Click "Create App"
4. Connect GitHub repository
5. DigitalOcean auto-detects Python app
6. Deploy!

---

## VPS Deployment (Advanced)

For more control, deploy on a VPS:

### Step 1: Get a VPS

- **DigitalOcean Droplet**: $6/month
- **Linode**: $5/month  
- **Vultr**: $5/month

### Step 2: Server Setup

```bash
# SSH into your server
ssh root@your-server-ip

# Install Python and dependencies
apt update
apt install python3 python3-pip nginx git -y

# Clone your repository
git clone https://github.com/yourusername/smc-api.git
cd smc-api

# Install Python dependencies
pip3 install -r requirements.txt

# Install PM2 for process management
npm install -g pm2
```

### Step 3: Configure PM2

```bash
# Create PM2 ecosystem file
cat > ecosystem.config.js << EOF
module.exports = {
  apps: [{
    name: 'smc-api',
    script: 'gunicorn',
    args: '--bind 0.0.0.0:8000 app:app --workers 2',
    interpreter: 'python3',
    env: {
      PORT: 8000,
      FLASK_ENV: 'production'
    }
  }]
}
EOF

# Start with PM2
pm2 start ecosystem.config.js
pm2 startup
pm2 save
```

### Step 4: Configure Nginx

```bash
cat > /etc/nginx/sites-available/smc-api << EOF
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF

ln -s /etc/nginx/sites-available/smc-api /etc/nginx/sites-enabled/
nginx -t
systemctl restart nginx
```

---

## Testing Your Live API

Once deployed, test all endpoints:

```bash
# Health check
curl https://your-live-url/health

# Symbols list
curl https://your-live-url/symbols

# Chart data
curl -X POST https://your-live-url/chart-data \
  -H "Content-Type: application/json" \
  -d '{"symbol": "TSLA", "timeframes": ["1d"]}'
```

---

## Monitoring & Maintenance

### Railway/Render/DigitalOcean App Platform
- Automatic scaling
- Built-in monitoring
- Automatic restarts
- HTTPS included

### VPS
- Monitor with `pm2 monit`
- Check logs with `pm2 logs`
- Restart with `pm2 restart smc-api`
- Set up monitoring (optional): New Relic, DataDog

---

## Cost Comparison

| Platform | Cost | Pros | Cons |
|----------|------|------|------|
| Railway | Free/$5+/month | Easiest, auto-scaling | Limited free tier |
| Render | Free/$7+/month | Good free tier | Slower cold starts |
| DigitalOcean | $10+/month | No cold starts | Requires setup |
| VPS | $5+/month | Full control | More maintenance |

**Recommendation**: Start with Railway for simplicity, then move to VPS if you need more control.
