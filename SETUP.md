# Setup

For full setup instructions (Python 3.11+, Poetry, Ollama or cloud API, .env, and run commands), see:

**[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)**

Quick summary: install Poetry and Python 3.11+, run `poetry install`, copy `.env.example` to `.env`, add Alpaca and LLM keys (or use Ollama), then `poetry run python src/main.py --tickers AAPL,MSFT,GOOGL`.

## Git commit identity

This repo is owned by **[github.com/Adi1yer](https://github.com/Adi1yer)**. After cloning, set **repo-local** git identity so pushes and commits show under that account (not a similarly named unrelated GitHub user):

```bash
cd Aletheia-Capital   # or your clone path
git config --local user.name "Adi1yer"
git config --local user.email "201507252+Adi1yer@users.noreply.github.com"
```

Verify:

```bash
git config --local user.name
git config --local user.email
```

On GitHub → **Adi1yer** → Settings → Emails, confirm `201507252+Adi1yer@users.noreply.github.com` appears (or enable “Keep my email addresses private” to use that noreply format).

**Avoid** `adityaiyer@users.noreply.github.com` and other generic noreply addresses — GitHub can attribute those commits to [github.com/AdityaIyer](https://github.com/AdityaIyer), which is a **different account** from this project.
