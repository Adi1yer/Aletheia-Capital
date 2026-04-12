# Getting Started

One place for environment setup. For architecture, API reference, and deployment, see the other files in `docs/`.

## Prerequisites

- **Python 3.11+** (required by project)
- **Poetry** (package manager)
- **Alpaca account** (paper trading) – [alpaca.markets](https://alpaca.markets/)
- **LLM**: local (Ollama) or cloud (DeepSeek recommended for scale)

## 1. Install Python 3.11+

**macOS (Homebrew):**
```bash
brew install python@3.11
# or latest
brew install python@3.12
```

**macOS (pyenv):**
```bash
brew install pyenv
# Add to ~/.zshrc: pyenv init, then:
pyenv install 3.11.9
cd /path/to/ai-hedge-fund-production
pyenv local 3.11.9
```

**Windows:** Download from [python.org](https://www.python.org/downloads/).

Verify: `python3 --version` or `python3.11 --version`.

## 2. Install Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

Add to PATH (e.g. in `~/.zshrc`): `export PATH="$HOME/.local/bin:$PATH"`, then `source ~/.zshrc`.

**Alternatives:** `pipx install poetry` or `brew install poetry` (macOS).

Verify: `poetry --version`. Tell Poetry to use Python 3.11: `poetry env use python3.11` (in project dir).

## 3. Install project dependencies

```bash
cd ai-hedge-fund-production
poetry install
```

## 4. Environment variables

```bash
cp .env.example .env
```

Edit `.env` with at least:

- **Alpaca (paper trading):** `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL=https://paper-api.alpaca.markets/v2`
- **LLM (pick one):**
  - **Ollama (local, free):** Install from [ollama.com](https://ollama.com/download), then `ollama pull llama3.1`. No key needed.
  - **DeepSeek (cloud, scale):** `DEEPSEEK_API_KEY` – good for large universes (see `CLOUD_SCALING_ANALYSIS.md`).

Optional: `GROQ_API_KEY`, email settings for notifications (see `EMAIL_SETUP.md`).

## 5. Run the system

**Weekly trading (dry run):**
```bash
poetry run python src/main.py --tickers AAPL,MSFT,GOOGL
```

**With trade execution (paper):**
```bash
poetry run python src/main.py --tickers AAPL,MSFT,GOOGL --execute
```

**Larger universe:**
```bash
poetry run python src/main.py --universe --max-stocks 100
```

**Daily update:**
```bash
poetry run python src/daily_update.py
```

**Backtest:**
```bash
poetry run python src/backtest.py --tickers AAPL,MSFT --start-date 2024-01-01 --end-date 2024-06-30
```

## Quick Ollama-only path

If you only use Ollama (no cloud API):

1. Install Ollama: [ollama.com/download](https://ollama.com/download) → drag to Applications → open Ollama.
2. Pull model: `ollama pull llama3.1`.
3. Run: `poetry run python src/main.py --tickers AAPL,MSFT,GOOGL`.

See `QUICK_START_OLLAMA.md` and `install_ollama.sh` in the project root for more.

## Troubleshooting

- **Poetry / Python version:** Ensure `poetry env use python3.11` and `python3.11 --version` works in the project directory.
- **Ollama "connection refused":** Start the Ollama app and wait a few seconds; then `curl http://localhost:11434/api/tags`.
- **Alpaca errors:** Use paper keys and `ALPACA_BASE_URL=https://paper-api.alpaca.markets/v2`. Keys are optional for dry runs.

## Next steps

- **Architecture:** `docs/ARCHITECTURE.md`
- **API reference:** `docs/API.md`
- **Deployment:** `docs/DEPLOYMENT.md`
- **Data sources (including insider data):** `docs/DATA_SOURCES.md`
