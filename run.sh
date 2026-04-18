#!/bin/bash
# Helper script to run commands with proper environment setup

# Set up environment
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)" 2>/dev/null || true

export PATH="$HOME/.local/bin:$PATH"

# Change to project directory
cd "$(dirname "$0")"

# Run the command
if [ "$1" == "test" ]; then
    poetry run pytest tests/ -v "${@:2}"
elif [ "$1" == "trade" ]; then
    poetry run python src/main.py "${@:2}"
elif [ "$1" == "smoke" ]; then
    poetry run python scripts/pipeline_smoke_check.py "${@:2}"
elif [ "$1" == "backtest" ]; then
    poetry run python src/backtest.py "${@:2}"
else
    poetry run "$@"
fi

