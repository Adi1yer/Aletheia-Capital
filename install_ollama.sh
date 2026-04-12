#!/bin/bash
# Quick Ollama installation and setup script for macOS

echo "🚀 Ollama Setup for AI Hedge Fund"
echo "=================================="
echo ""

# Check if Ollama is already installed
if command -v ollama &> /dev/null; then
    echo "✅ Ollama is already installed"
    ollama --version
else
    echo "📥 Ollama not found. Please install it:"
    echo ""
    echo "Option 1: Download from website (Recommended)"
    echo "  1. Visit: https://ollama.com/download"
    echo "  2. Download the macOS .dmg file"
    echo "  3. Open and drag Ollama to Applications"
    echo "  4. Open Ollama from Applications"
    echo ""
    echo "Option 2: Install via Homebrew (if you have it)"
    echo "  brew install ollama"
    echo ""
    read -p "Press Enter after you've installed Ollama..."
fi

# Check if Ollama is running
echo ""
echo "Checking if Ollama is running..."
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✅ Ollama is running!"
else
    echo "⚠️  Ollama is not running"
    echo "Please start Ollama:"
    echo "  - Open Ollama from Applications, or"
    echo "  - Run: open -a Ollama"
    echo ""
    read -p "Press Enter after Ollama is running..."
fi

# Pull required models
echo ""
echo "Pulling required models..."
echo "This may take a few minutes depending on your internet speed..."
echo ""

if ollama pull llama3.1; then
    echo "✅ llama3.1 model downloaded"
else
    echo "❌ Failed to download llama3.1"
    echo "You can try manually: ollama pull llama3.1"
fi

# Verify setup
echo ""
echo "Verifying setup..."
if curl -s http://localhost:11434/api/tags | grep -q "llama3.1"; then
    echo "✅ Setup complete! Ollama is ready to use."
    echo ""
    echo "You can now run:"
    echo "  poetry run python src/main.py --tickers AAPL,MSFT,GOOGL"
else
    echo "⚠️  Setup may not be complete. Please verify:"
    echo "  1. Ollama is running"
    echo "  2. llama3.1 model is downloaded: ollama pull llama3.1"
fi

