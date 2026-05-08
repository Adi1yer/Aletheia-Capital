#!/usr/bin/env python3
"""Read-only connectivity checks for trading workflows."""

from __future__ import annotations

import argparse
import smtplib
from pathlib import Path
from typing import Callable

import requests
import structlog
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from src.config.settings import settings
from src.llm.models import get_llm_for_agent

load_dotenv(Path(__file__).resolve().parent / ".env")

logger = structlog.get_logger()


def _alpaca_account_request(api_key: str, secret_key: str) -> dict:
    # Intentionally uses direct REST instead of importing src.broker.alpaca / alpaca.trading.*
    # because those SDK import paths segfault (exit 139) in some local environments.
    # Keep preflight read-only and runtime-stable by checking account connectivity via HTTPS.
    resp = requests.get(
        "https://paper-api.alpaca.markets/v2/account",
        headers={
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        },
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict) or "equity" not in payload:
        raise RuntimeError("Unexpected Alpaca account payload")
    return payload


def _check_main_alpaca() -> None:
    logger.info("MAIN CHECK: Alpaca account lookup")
    key = (settings.alpaca_api_key or "").strip()
    sec = (settings.alpaca_secret_key or "").strip()
    if not key or not sec:
        raise RuntimeError("Missing ALPACA_API_KEY and/or ALPACA_SECRET_KEY")
    account = _alpaca_account_request(key, sec)
    logger.info("MAIN OK", equity=account.get("equity"), cash=account.get("cash"))


def _check_biotech_alpaca() -> None:
    logger.info("BIOTECH CHECK: Alpaca account lookup")
    key = (settings.biotech_alpaca_api_key or "").strip()
    sec = (settings.biotech_alpaca_secret_key or "").strip()
    if not key or not sec:
        raise RuntimeError("Missing BIOTECH_ALPACA_API_KEY and/or BIOTECH_ALPACA_SECRET_KEY")
    account = _alpaca_account_request(key, sec)
    logger.info("BIOTECH OK", equity=account.get("equity"), cash=account.get("cash"))


def _check_deepseek() -> None:
    logger.info("DEEPSEEK CHECK: model invoke")
    api_key = (settings.deepseek_api_key or "").strip()
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY")
    llm = get_llm_for_agent("deepseek-v3", "deepseek")
    # Tiny prompt verifies auth/connectivity without incurring meaningful usage.
    _ = llm.bind(max_tokens=1).invoke([HumanMessage(content="respond with OK")])
    logger.info("DEEPSEEK OK")


def _check_smtp() -> None:
    logger.info("SMTP CHECK: starttls + login")
    server = (settings.smtp_server or "").strip()
    port = int(settings.smtp_port)
    sender = (settings.sender_email or "").strip()
    pwd = (settings.sender_password or "").strip()
    if not server or not sender or not pwd:
        raise RuntimeError("Missing SMTP_SERVER/SENDER_EMAIL/SENDER_PASSWORD")
    with smtplib.SMTP(server, port, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(sender, pwd)
    logger.info("SMTP OK", server=server, port=port)


def _check_finnhub() -> None:
    logger.info("FINNHUB CHECK: lightweight quote request")
    key = (settings.finnhub_api_key or "").strip()
    if not key:
        logger.warning("FINNHUB SKIP: FINNHUB_API_KEY not set")
        return
    resp = requests.get(
        "https://finnhub.io/api/v1/quote",
        params={"symbol": "AAPL", "token": key},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict) or "c" not in payload:
        raise RuntimeError("Unexpected Finnhub response payload")
    logger.info("FINNHUB OK")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Preflight connectivity checks (read-only)")
    p.add_argument("--skip-deepseek", action="store_true", help="Skip DeepSeek check")
    p.add_argument("--skip-smtp", action="store_true", help="Skip SMTP login check")
    p.add_argument("--skip-finnhub", action="store_true", help="Skip Finnhub check")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    checks: list[tuple[str, Callable[[], None]]] = [
        ("main_alpaca", _check_main_alpaca),
        ("biotech_alpaca", _check_biotech_alpaca),
    ]
    if not args.skip_deepseek:
        checks.append(("deepseek", _check_deepseek))
    if not args.skip_smtp:
        checks.append(("smtp", _check_smtp))
    if not args.skip_finnhub:
        checks.append(("finnhub", _check_finnhub))

    failures: list[tuple[str, str]] = []
    for name, check in checks:
        try:
            check()
        except Exception as exc:  # pragma: no cover - exercised in tests via mocks
            failures.append((name, str(exc)))
            logger.error("CHECK FAILED", check=name, error=str(exc))

    if failures:
        logger.error("PREFLIGHT FAILED", failed=[n for n, _ in failures])
        for name, error in failures:
            print(f"[FAIL] {name}: {error}")
        return 1

    logger.info("PREFLIGHT OK")
    print("Preflight checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
