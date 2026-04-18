# Email Notifications Setup

## Overview

The system can send email notifications for:
- **Daily Market Updates**: Portfolio status, market summary, holdings data
- **Weekly Trading Results**: Trading decisions, execution results, portfolio status

## Setup

### 1. Gmail Setup (Recommended)

1. **Enable 2-Factor Authentication** on your Gmail account
2. **Generate App Password**:
   - Go to Google Account settings
   - Security → 2-Step Verification → App passwords
   - Generate password for "Mail"
   - Copy the 16-character password

3. **Add to `.env` file**:
```bash
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SENDER_EMAIL=your-email@gmail.com
SENDER_PASSWORD=your-16-char-app-password
RECIPIENT_EMAIL=recipient@example.com
```

### 2. Other Email Providers

#### Outlook/Hotmail
```bash
SMTP_SERVER=smtp-mail.outlook.com
SMTP_PORT=587
SENDER_EMAIL=your-email@outlook.com
SENDER_PASSWORD=your-password
```

#### Yahoo Mail
```bash
SMTP_SERVER=smtp.mail.yahoo.com
SMTP_PORT=587
SENDER_EMAIL=your-email@yahoo.com
SENDER_PASSWORD=your-app-password
```

#### Custom SMTP
```bash
SMTP_SERVER=your-smtp-server.com
SMTP_PORT=587
SENDER_EMAIL=your-email@domain.com
SENDER_PASSWORD=your-password
```

## Usage

### Weekly Trading with Email

```bash
# Send trading results via email
poetry run python src/main.py --universe --max-stocks 2000 --execute --email

# Send to specific recipient
poetry run python src/main.py --tickers AAPL,MSFT --execute --email --email-to custom@example.com
```

## Automated Email Notifications

### Cron Setup for Weekly Trading with Email

```bash
# Weekly trading on Monday at 9 AM with email
0 9 * * 1 cd /path/to/ai-hedge-fund-production && poetry run python src/main.py --universe --max-stocks 2000 --execute --email
```

## Email Format

### Daily Update Email Includes:
- Portfolio status (cash, equity, positions)
- Market summary (S&P 500, NASDAQ, Dow)
- Top holdings with price changes
- Agent status

### Trading Results Email Includes:
- Trading summary (tickers analyzed, decisions made)
- Portfolio status
- Top trading decisions (sorted by confidence)
- Execution results

Both emails are sent in **HTML format** with tables and color coding for easy reading.

## Troubleshooting

### "Email notifier not configured"
- Check that all email settings are in `.env`
- Verify SMTP server and port are correct
- For Gmail, make sure you're using an app password, not your regular password

### "Failed to send email"
- Check internet connection
- Verify SMTP credentials
- Check firewall settings
- For Gmail, ensure "Less secure app access" is enabled OR use app password

### Test Email Configuration

You can test by running:
```bash
poetry run python -c "from src.utils.email import get_email_notifier; n = get_email_notifier(); n.send_email('test@example.com', 'Test', 'This is a test email')"
```

## Security Notes

- **Never commit `.env` file** to git
- Use **app passwords** instead of main passwords when possible
- Consider using environment variables in production instead of `.env` file
- For production, consider using email services like SendGrid, Mailgun, or AWS SES

