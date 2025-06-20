#!/bin/bash

# Quick deployment script for Smart Money Concepts API

echo "🚀 Smart Money Concepts API - Quick Deploy Script"
echo "=================================================="

# Check if git is initialized
if [ ! -d ".git" ]; then
    echo "📁 Initializing git repository..."
    git init
    git add .
    git commit -m "Initial commit: Smart Money Concepts API"
    echo "✅ Git repository initialized"
else
    echo "📁 Git repository already exists"
    echo "💾 Adding latest changes..."
    git add .
    git commit -m "Updated: Smart Money Concepts API $(date)"
fi

echo ""
echo "🎯 Next Steps for 24/7 Deployment:"
echo ""
echo "1. 📤 Push to GitHub:"
echo "   - Create a new repository on GitHub"
echo "   - Copy this command (replace with your GitHub URL):"
echo "   git remote add origin https://github.com/yourusername/smc-api.git"
echo "   git branch -M main"
echo "   git push -u origin main"
echo ""
echo "2. 🚀 Deploy on Railway (Recommended):"
echo "   - Go to: https://railway.app"
echo "   - Sign up with GitHub"
echo "   - Click 'New Project' → 'Deploy from GitHub repo'"
echo "   - Select your repository"
echo "   - Railway will auto-deploy!"
echo ""
echo "3. 🧪 Test your live API:"
echo "   python test_live_api.py https://your-app-name.railway.app"
echo ""
echo "4. 📡 Use your live API endpoints:"
echo "   - Health: https://your-app-name.railway.app/health"
echo "   - Symbols: https://your-app-name.railway.app/symbols"
echo "   - Analysis: https://your-app-name.railway.app/chart-data"
echo ""
echo "💡 Your API will be live 24/7 and ready for webhook requests!"
echo ""
echo "📖 For detailed instructions, see DEPLOYMENT.md"
