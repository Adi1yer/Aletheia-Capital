#!/usr/bin/env python3
"""Send consolidated weekly email for satellite workflow sleeves."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

import structlog

from src.config.settings import settings
from src.fund.orchestrator import run_orchestrator
from src.fund.sleeve_digest import build_sleeve_digest, format_digest_markdown
from src.utils.email import get_email_notifier

logger = structlog.get_logger()


def main() -> int:
    p = argparse.ArgumentParser(description="Fund satellite sleeve weekly digest email")
    p.add_argument("--no-email", action="store_true")
    p.add_argument("--email-to", type=str, default="")
    args = p.parse_args()

    run_orchestrator()
    digest = build_sleeve_digest()
    body = format_digest_markdown(digest)
    print(body)

    if args.no_email:
        return 0

    recipient = (
        args.email_to.strip()
        or (settings.recipient_email or "").strip()
    )
    if not recipient:
        logger.error("No recipient email configured")
        return 1

    subject = (
        f"Satellite Sleeve Digest — {digest.get('run_date')} "
        f"(${digest.get('total_satellite_equity', 0):,.0f} total)"
    )
    html = (
        '<html><body><pre style="white-space:pre-wrap;font-family:Arial,sans-serif;">'
        + body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        + "</pre></body></html>"
    )
    sent = get_email_notifier().send_email(
        recipient=recipient,
        subject=subject,
        body_text=body,
        body_html=html,
    )
    logger.info("Digest email sent", recipient=recipient, sent=bool(sent))
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
