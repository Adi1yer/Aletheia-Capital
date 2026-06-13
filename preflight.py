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

from src.broker.registry import (
    get_alpaca_credentials,
    get_workflow,
    list_physical_accounts,
    workflow_credentials_configured,
)
from src.config.settings import settings
from src.llm.models import get_llm_for_agent

load_dotenv(Path(__file__).resolve().parent / ".env")

logger = structlog.get_logger()


def _alpaca_account_request(api_key: str, secret_key: str) -> dict:
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


def _check_workflow_alpaca(workflow_id: str, api_key: str, secret_key: str) -> None:
    logger.info("ALPACA CHECK", workflow=workflow_id)
    if not api_key or not secret_key:
        raise RuntimeError(f"Missing keys for {workflow_id}")
    account = _alpaca_account_request(api_key, secret_key)
    logger.info("ALPACA OK", workflow=workflow_id, equity=account.get("equity"))


def _check_all_configured_alpaca() -> None:
    checked: set[str] = set()
    for wf in list_physical_accounts(enabled_only=True):
        if wf.broker != "alpaca":
            continue
        prefix = wf.physical_account_key
        if prefix in checked:
            continue
        checked.add(prefix)
        key, sec = get_alpaca_credentials(wf)
        _check_workflow_alpaca(wf.workflow_id, key, sec)


def _check_workflow_account_alpaca(workflow_id: str) -> None:
    wf = get_workflow(workflow_id)
    if wf is None:
        raise RuntimeError(f"Unknown workflow: {workflow_id}")
    key, sec = get_alpaca_credentials(wf)
    _check_workflow_alpaca(workflow_id, key, sec)


def _check_satellite_alpaca() -> None:
    wf = get_workflow("hedge-weekly")
    if wf is None:
        raise RuntimeError("hedge-weekly not in registry")
    if not workflow_credentials_configured(wf):
        raise RuntimeError(
            "Satellite Alpaca credentials not configured "
            "(set MULTI_SLEEVE_ALPACA_* or HEDGE_ALPACA_*)"
        )
    key, sec = get_alpaca_credentials(wf)
    _check_workflow_alpaca("multi_sleeve", key, sec)


def _check_main_alpaca() -> None:
    _check_workflow_account_alpaca("weekly-scan")


def _check_biotech_alpaca() -> None:
    _check_workflow_account_alpaca("biotech-catalyst")


def _check_deepseek() -> None:
    logger.info("DEEPSEEK CHECK: model invoke")
    api_key = (settings.deepseek_api_key or "").strip()
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY")
    llm = get_llm_for_agent("deepseek-v3", "deepseek")
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
    p.add_argument("--skip-deepseek", action="store_true")
    p.add_argument("--skip-smtp", action="store_true")
    p.add_argument("--skip-finnhub", action="store_true")
    p.add_argument("--skip-biotech", action="store_true")
    p.add_argument("--skip-main", action="store_true", help="Skip main equity Alpaca check")
    p.add_argument("--all-workflows", action="store_true", help="Ping every configured Alpaca workflow")
    p.add_argument(
        "--satellite-only",
        action="store_true",
        help="Ping shared multi-sleeve Alpaca account only (hedge/options/congressional/macro/crypto)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    checks: list[tuple[str, Callable[[], None]]] = []
    if args.all_workflows:
        checks = [("all_alpaca_workflows", _check_all_configured_alpaca)]
    elif args.satellite_only:
        checks = [("satellite_alpaca", _check_satellite_alpaca)]
    else:
        if not args.skip_main:
            checks.append(("main_alpaca", _check_main_alpaca))
        if not args.skip_biotech:
            checks.append(("biotech_alpaca", _check_biotech_alpaca))
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
        except Exception as exc:
            failures.append((name, str(exc)))
            logger.error("CHECK FAILED", check=name, error=str(exc))

    if failures:
        for name, error in failures:
            print(f"[FAIL] {name}: {error}")
        return 1

    print("Preflight checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
