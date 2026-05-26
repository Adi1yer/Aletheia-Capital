"""Optional webhook alerts for critical pipeline events."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import requests
import structlog

logger = structlog.get_logger()


def send_alert(title: str, body: str, extra: Optional[Dict[str, Any]] = None) -> bool:
    url = (os.environ.get("ALERT_WEBHOOK_URL") or "").strip()
    if not url:
        return False
    payload = {"title": title, "body": body, "extra": extra or {}}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.warning("Webhook alert failed", error=str(e))
        return False
