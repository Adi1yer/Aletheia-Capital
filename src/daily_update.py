"""Daily market update script"""

import argparse
import structlog
from src.trading.daily_updates import DailyUpdateSystem
from src.config.settings import settings
from src.utils.email import get_email_notifier

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(settings.log_level),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)

logger = structlog.get_logger()


def main():
    """Generate daily market update"""
    parser = argparse.ArgumentParser(description="Daily Market Update System")
    parser.add_argument(
        "--output",
        type=str,
        choices=["console", "json", "both"],
        default="console",
        help="Output format (default: console)",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Save update to file (JSON format)",
    )
    parser.add_argument(
        "--email",
        action="store_true",
        help="Send update via email",
    )
    parser.add_argument(
        "--email-to",
        type=str,
        help="Email recipient (overrides config default)",
    )
    
    args = parser.parse_args()
    
    logger.info("Generating daily market update")
    
    # Generate update
    update_system = DailyUpdateSystem()
    update = update_system.generate_daily_update(market_summary=True)
    
    # Format report for email/console
    report = update_system.format_update_report(update)
    
    # Output based on format
    if args.output in ["console", "both"]:
        print(report)
    
    if args.output in ["json", "both"]:
        import json
        json_output = json.dumps(update, indent=2, default=str)
        if args.file:
            with open(args.file, 'w') as f:
                f.write(json_output)
            logger.info("Update saved to file", file=args.file)
        else:
            print("\n" + "="*80)
            print("JSON OUTPUT")
            print("="*80)
            print(json_output)
    
    # Send email if requested
    if args.email or args.email_to:
        recipient = args.email_to or settings.recipient_email
        if recipient:
            email_notifier = get_email_notifier()
            email_notifier.send_daily_update(recipient, update, report)
            logger.info("Daily update email sent", recipient=recipient)
        else:
            logger.warning("No email recipient specified")
    
    logger.info("Daily update complete")


if __name__ == "__main__":
    main()

