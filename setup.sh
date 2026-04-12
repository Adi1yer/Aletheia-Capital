#!/bin/bash
# Automated setup script for AI Hedge Fund Production System

set -e  # Exit on error

echo "🚀 AI Hedge Fund Production System - Setup Script"
echo "=================================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check Python version
check_python() {
    echo "Checking Python version..."
    if command -v python3.11 &> /dev/null; then
        PYTHON_CMD="python3.11"
        PYTHON_VERSION=$(python3.11 --version 2>&1 | awk '{print $2}')
        echo -e "${GREEN}✓ Found Python $PYTHON_VERSION${NC}"
        return 0
    elif command -v python3.12 &> /dev/null; then
        PYTHON_CMD="python3.12"
        PYTHON_VERSION=$(python3.12 --version 2>&1 | awk '{print $2}')
        echo -e "${GREEN}✓ Found Python $PYTHON_VERSION${NC}"
        return 0
    elif command -v python3.13 &> /dev/null; then
        PYTHON_CMD="python3.13"
        PYTHON_VERSION=$(python3.13 --version 2>&1 | awk '{print $2}')
        echo -e "${GREEN}✓ Found Python $PYTHON_VERSION${NC}"
        return 0
    else
        CURRENT_PYTHON=$(python3 --version 2>&1 | awk '{print $2}')
        echo -e "${RED}✗ Python 3.11+ required, but found Python $CURRENT_PYTHON${NC}"
        echo -e "${YELLOW}Please install Python 3.11+ first:${NC}"
        echo "  - Homebrew: brew install python@3.11"
        echo "  - pyenv: pyenv install 3.11.9"
        echo "  - Or download from https://www.python.org/downloads/"
        return 1
    fi
}

# Install Poetry if not present
install_poetry() {
    echo ""
    echo "Checking Poetry installation..."
    if command -v poetry &> /dev/null; then
        POETRY_VERSION=$(poetry --version | awk '{print $3}')
        echo -e "${GREEN}✓ Poetry $POETRY_VERSION already installed${NC}"
    else
        echo "Installing Poetry..."
        if command -v pipx &> /dev/null; then
            pipx install poetry
        else
            curl -sSL https://install.python-poetry.org | $PYTHON_CMD -
            export PATH="$HOME/.local/bin:$PATH"
        fi
        echo -e "${GREEN}✓ Poetry installed${NC}"
    fi
}

# Configure Poetry environment
configure_poetry() {
    echo ""
    echo "Configuring Poetry environment..."
    export PATH="$HOME/.local/bin:$PATH"
    
    # Set Poetry to use the correct Python version
    if [ -n "$PYTHON_CMD" ]; then
        poetry env use $PYTHON_CMD || {
            echo -e "${YELLOW}⚠ Could not set Poetry environment, continuing...${NC}"
        }
    fi
    
    echo -e "${GREEN}✓ Poetry configured${NC}"
}

# Install project dependencies
install_dependencies() {
    echo ""
    echo "Installing project dependencies..."
    export PATH="$HOME/.local/bin:$PATH"
    
    # Install base dependencies
    poetry install || {
        echo -e "${RED}✗ Failed to install dependencies${NC}"
        echo "Trying with verbose output..."
        poetry install -v
        return 1
    }
    
    echo -e "${GREEN}✓ Dependencies installed${NC}"
}

# Optional: Install Redis support
install_redis_support() {
    echo ""
    read -p "Install Redis caching support? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Installing Redis support..."
        poetry install --extras redis || {
            echo -e "${YELLOW}⚠ Redis support installation failed (optional)${NC}"
        }
        echo -e "${GREEN}✓ Redis support installed${NC}"
    fi
}

# Run tests
run_tests() {
    echo ""
    read -p "Run tests now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Running tests..."
        export PATH="$HOME/.local/bin:$PATH"
        poetry run pytest tests/ -v || {
            echo -e "${YELLOW}⚠ Some tests failed (check output above)${NC}"
        }
    fi
}

# Main execution
main() {
    # Check Python
    if ! check_python; then
        exit 1
    fi
    
    # Install Poetry
    install_poetry
    
    # Configure Poetry
    configure_poetry
    
    # Install dependencies
    if ! install_dependencies; then
        echo -e "${RED}✗ Setup failed during dependency installation${NC}"
        exit 1
    fi
    
    # Optional: Install Redis support
    install_redis_support
    
    # Optional: Run tests
    run_tests
    
    echo ""
    echo -e "${GREEN}✅ Setup complete!${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Add Poetry to your PATH (if not already):"
    echo "     echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc"
    echo "     source ~/.zshrc"
    echo ""
    echo "  2. Run the trading system:"
    echo "     poetry run python src/main.py --tickers AAPL,MSFT,GOOGL"
    echo ""
    echo "  3. Get daily updates:"
    echo "     poetry run python src/daily_update.py"
    echo ""
}

# Run main function
main

