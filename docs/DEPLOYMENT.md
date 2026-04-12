# Deployment Guide

## Overview

This guide covers deploying the AI Hedge Fund Production System in various environments, from local development to cloud production.

## Prerequisites

- Python 3.11+
- Poetry (package manager)
- Alpaca paper trading account
- (Optional) Redis for distributed caching
- (Optional) SMTP server for email notifications

## Local Deployment

### 1. Installation

```bash
# Clone/navigate to project
cd ai-hedge-fund-production

# Install dependencies
poetry install

# Set up environment variables
cp .env.example .env
# Edit .env with your API keys
```

### 2. Configuration

Edit `.env` file:

```bash
# Required: Alpaca API keys
ALPACA_API_KEY=your-api-key
ALPACA_SECRET_KEY=your-secret-key
ALPACA_BASE_URL=https://paper-api.alpaca.markets/v2

# Optional: LLM API keys
DEEPSEEK_API_KEY=your-deepseek-key
GROQ_API_KEY=your-groq-key

# Optional: Email notifications
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SENDER_EMAIL=your-email@gmail.com
SENDER_PASSWORD=your-app-password
RECIPIENT_EMAIL=recipient@example.com

# Optional: Redis for caching
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=
```

### 3. Running the System

#### Weekly Trading
```bash
# Dry run (no trades executed)
poetry run python src/main.py --tickers AAPL,MSFT,GOOGL

# Execute trades
poetry run python src/main.py --tickers AAPL,MSFT,GOOGL --execute

# Full market trading
poetry run python src/main.py --universe --max-stocks 2000 --execute
```

#### Daily Updates
```bash
# Console output
poetry run python src/daily_update.py

# JSON output
poetry run python src/daily_update.py --output json --file logs/daily_update.json

# Email notification
poetry run python src/daily_update.py --email
```

### 4. Scheduling (Cron)

Use the `scripts/run_weekly_scan.sh` wrapper for easier configuration and logging.

#### Weekly Trading (Sunday 6 PM recommended)
```bash
# Edit crontab
crontab -e

# Add line (dry run with default tickers):
0 18 * * 0 cd /path/to/ai-hedge-fund-production && ./scripts/run_weekly_scan.sh

# Or with execution and email to a specific address:
0 18 * * 0 cd /path/to/ai-hedge-fund-production && ./scripts/run_weekly_scan.sh --tickers AAPL,MSFT,GOOGL --execute --email-to aditya.iyer@gmail.com

# Full universe (recommend DEEPSEEK_API_KEY in .env for 100+ tickers):
0 18 * * 0 cd /path/to/ai-hedge-fund-production && ./scripts/run_weekly_scan.sh --universe --max-stocks 200 --execute --email-to aditya.iyer@gmail.com
```

Make the script executable first: `chmod +x scripts/run_weekly_scan.sh`

#### Direct Python (alternative)
```bash
0 9 * * 1 cd /path/to/ai-hedge-fund-production && poetry run python src/main.py --universe --max-stocks 2000 --execute --email >> logs/weekly_trading.log 2>&1
```

#### Daily Updates (Every day at 5 PM)
```bash
0 17 * * * cd /path/to/ai-hedge-fund-production && poetry run python src/daily_update.py --email >> logs/daily_update.log 2>&1
```

## Cloud Deployment

### Option 1: Railway

1. **Create Railway Account**
   - Sign up at [railway.app](https://railway.app)

2. **Create New Project**
   - Click "New Project"
   - Select "Deploy from GitHub repo"

3. **Configure Environment Variables**
   - Go to Variables tab
   - Add all required `.env` variables

4. **Deploy**
   - Railway will auto-detect Python
   - Install dependencies via Poetry
   - Run on schedule using Railway Cron

5. **Scheduled Jobs**
   - Use Railway Cron for weekly trading
   - Use Railway Cron for daily updates

### Option 2: AWS EC2

1. **Launch EC2 Instance**
   ```bash
   # Ubuntu 22.04 LTS recommended
   # t3.medium or larger
   ```

2. **Install Dependencies**
   ```bash
   # Install Python 3.11
   sudo apt update
   sudo apt install python3.11 python3.11-venv python3-pip

   # Install Poetry
   curl -sSL https://install.python-poetry.org | python3 -

   # Clone repository
   git clone <your-repo-url>
   cd ai-hedge-fund-production

   # Install dependencies
   poetry install
   ```

3. **Set Up Environment**
   ```bash
   # Create .env file
   nano .env
   # Add all environment variables
   ```

4. **Set Up Systemd Services**

   Create `/etc/systemd/system/hedge-fund-weekly.service`:
   ```ini
   [Unit]
   Description=AI Hedge Fund Weekly Trading
   After=network.target

   [Service]
   Type=oneshot
   User=ubuntu
   WorkingDirectory=/home/ubuntu/ai-hedge-fund-production
   Environment="PATH=/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin"
   ExecStart=/home/ubuntu/.local/bin/poetry run python src/main.py --universe --max-stocks 2000 --execute --email
   StandardOutput=append:/home/ubuntu/ai-hedge-fund-production/logs/weekly.log
   StandardError=append:/home/ubuntu/ai-hedge-fund-production/logs/weekly.error.log
   ```

   Create `/etc/systemd/system/hedge-fund-weekly.timer`:
   ```ini
   [Unit]
   Description=Run weekly trading every Monday at 9 AM
   Requires=hedge-fund-weekly.service

   [Timer]
   OnCalendar=Mon *-*-* 09:00:00
   Persistent=true

   [Install]
   WantedBy=timers.target
   ```

   Enable and start:
   ```bash
   sudo systemctl enable hedge-fund-weekly.timer
   sudo systemctl start hedge-fund-weekly.timer
   ```

### Option 3: Docker

1. **Create Dockerfile**
   ```dockerfile
   FROM python:3.11-slim

   WORKDIR /app

   # Install Poetry
   RUN pip install poetry

   # Copy dependency files
   COPY pyproject.toml poetry.lock ./

   # Install dependencies
   RUN poetry config virtualenvs.create false && \
       poetry install --no-dev

   # Copy application code
   COPY . .

   # Run application
   CMD ["poetry", "run", "python", "src/main.py", "--universe", "--max-stocks", "2000", "--execute"]
   ```

2. **Create docker-compose.yml**
   ```yaml
   version: '3.8'

   services:
     hedge-fund:
       build: .
       environment:
         - ALPACA_API_KEY=${ALPACA_API_KEY}
         - ALPACA_SECRET_KEY=${ALPACA_SECRET_KEY}
         # ... other env vars
       volumes:
         - ./logs:/app/logs
         - ./config:/app/config
       restart: unless-stopped

     redis:
       image: redis:7-alpine
       ports:
         - "6379:6379"
       volumes:
         - redis-data:/data

   volumes:
     redis-data:
   ```

3. **Deploy**
   ```bash
   docker-compose up -d
   ```

## Redis Setup (Optional)

### Local Redis
```bash
# Install Redis
sudo apt install redis-server  # Ubuntu/Debian
brew install redis             # macOS

# Start Redis
redis-server

# Test connection
redis-cli ping  # Should return PONG
```

### Cloud Redis (Recommended for Production)

**AWS ElastiCache**:
- Create ElastiCache Redis cluster
- Use cluster endpoint in `REDIS_HOST`
- Configure security groups

**Redis Cloud**:
- Sign up at [redis.com](https://redis.com)
- Create free database
- Use connection string in environment

### Using Redis in Code

```python
import redis
from src.data.cache.redis import RedisCache

# Connect to Redis
redis_client = redis.Redis(
    host='localhost',
    port=6379,
    password=None,  # Set if required
    decode_responses=False
)

# Use in data aggregator
from src.data.providers.aggregator import DataAggregator
aggregator = DataAggregator(redis_client=redis_client)
```

## Monitoring

### Logs
- Weekly trading: `logs/weekly_trading.log`
- Daily updates: `logs/daily_update.log`
- Application logs: `logs/app.log`

### Health Checks
```bash
# Check if system is running
ps aux | grep python

# Check recent logs
tail -f logs/app.log

# Check scheduled jobs
systemctl list-timers  # Linux systemd
crontab -l            # Cron
```

### Alerts
- Set up email notifications for errors
- Monitor Alpaca account for issues
- Track API rate limits

## Performance Tuning

### For Large Universes (1000+ stocks)

1. **Enable Parallel Execution**
   ```python
   pipeline = TradingPipeline(parallel_agents=True, max_workers=8)
   ```

2. **Use Redis Caching**
   - Reduces API calls
   - Faster data retrieval

3. **Adjust Batch Sizes**
   ```python
   # In pipeline._run_agents()
   batch_size = 50  # Smaller batches for memory-constrained systems
   ```

4. **Limit Stock Universe**
   ```bash
   # Use max-stocks to limit universe size
   python src/main.py --universe --max-stocks 500
   ```

## Security Best Practices

1. **Environment Variables**
   - Never commit `.env` file
   - Use secrets management in cloud
   - Rotate API keys regularly

2. **API Keys**
   - Use paper trading keys only
   - Restrict API key permissions
   - Monitor API usage

3. **Network Security**
   - Use HTTPS for all API calls
   - Restrict Redis access (if used)
   - Use VPN for cloud deployments

4. **Error Handling**
   - System fails gracefully
   - No sensitive data in logs
   - Email alerts for critical errors

## Troubleshooting

### Common Issues

1. **Import Errors**
   ```bash
   # Reinstall dependencies
   poetry install
   ```

2. **API Rate Limits**
   - Reduce universe size
   - Increase cache TTL
   - Use Redis caching

3. **Memory Issues**
   - Reduce batch sizes
   - Limit universe size
   - Use Redis instead of memory cache

4. **Scheduled Jobs Not Running**
   - Check cron/systemd status
   - Verify file paths
   - Check permissions

## Backup and Recovery

### Configuration Backup
```bash
# Backup agent weights
cp config/agent_weights.json config/agent_weights.json.backup

# Backup logs
tar -czf logs_backup.tar.gz logs/
```

### Recovery
```bash
# Restore agent weights
cp config/agent_weights.json.backup config/agent_weights.json

# Restore logs
tar -xzf logs_backup.tar.gz
```

## Scaling Considerations

- **Horizontal Scaling**: Run multiple instances for different universes
- **Vertical Scaling**: Increase memory/CPU for larger universes
- **Database**: Consider PostgreSQL for performance tracking (future)
- **Message Queue**: Consider RabbitMQ/Kafka for async processing (future)

## Support

For issues or questions:
1. Check logs in `logs/` directory
2. Review documentation in `docs/`
3. Check GitHub issues
4. Contact support

