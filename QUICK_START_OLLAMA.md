# Quick Start with Ollama (Free LLM)

## ✅ Configuration Complete!

All 21 agents have been updated to use Ollama by default. The system is ready to use once Ollama is installed.

## Install Ollama (5 minutes)

### Step 1: Download Ollama
1. Visit: **https://ollama.com/download**
2. Download the **macOS** installer (.dmg file)
3. Open the .dmg file
4. Drag **Ollama** to your **Applications** folder

### Step 2: Start Ollama
1. Open **Ollama** from Applications
   - Or run: `open -a Ollama`
2. Wait a few seconds for it to start
3. You should see the Ollama icon in your menu bar

### Step 3: Download the Model
Open Terminal and run:
```bash
ollama pull llama3.1
```

This will download the llama3.1 model (~4.7GB). It may take a few minutes.

### Step 4: Verify
```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Test the model
ollama run llama3.1 "Hello, test"
```

## Run Your Trading System

Once Ollama is installed and running:

```bash
cd /Users/adityaiyer/ai-hedge-fund-production

# Set up environment
export PATH="/Users/adityaiyer/.local/bin:$PATH"
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"

# Run dry run
poetry run python src/main.py --tickers AAPL,MSFT,GOOGL
```

## What Changed

✅ All 21 agents now use `ollama-llama` by default  
✅ System will connect to `http://localhost:11434`  
✅ No API keys needed - completely free!  
✅ All LLM calls happen locally on your machine  

## Performance

- **First run**: Slower as models load into memory
- **Subsequent runs**: Faster as models stay in memory
- **Model size**: llama3.1 is ~4.7GB
- **Speed**: Depends on your Mac's RAM and CPU

## Troubleshooting

### "Connection refused" error
- Make sure Ollama is running: `open -a Ollama`
- Wait 10-15 seconds after starting
- Check: `curl http://localhost:11434/api/tags`

### "Model not found" error
- Pull the model: `ollama pull llama3.1`
- Wait for download to complete
- Verify: `ollama list` should show llama3.1

### Slow performance
- This is normal for local LLMs
- First analysis per ticker will be slower
- Subsequent analyses will be faster
- Consider using a smaller model: `ollama pull qwen2.5` (1.5GB)

## Alternative Models

If llama3.1 is too slow, try smaller models:

```bash
# Smaller, faster model
ollama pull qwen2.5

# Then update agents to use it (optional)
# The system will automatically use qwen2.5 if configured
```

## Next Steps

1. ✅ Install Ollama (download from website)
2. ✅ Start Ollama
3. ✅ Pull llama3.1 model
4. ✅ Run your trading system!

Everything is configured and ready to go! 🚀

