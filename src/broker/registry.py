"""Workflow → dedicated paper account registry."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import structlog
import yaml

logger = structlog.get_logger()

_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "workflow_accounts.yaml"


# Alpaca env prefixes tried in order when env_prefix is MULTI_SLEEVE_ALPACA (shared satellite book).
_MULTI_SLEEVE_ALPACA_FALLBACK_PREFIXES = (
    "MULTI_SLEEVE_ALPACA",
    "HEDGE_ALPACA",  # legacy: beta-hedge account reused for all satellite sleeves
)


@dataclass(frozen=True)
class WorkflowAccount:
    workflow_id: str
    broker: str
    env_prefix: str
    snapshot_subdir: str
    data_dir: str
    account_group: str = ""
    enabled: bool = True
    label: str = ""

    @property
    def physical_account_key(self) -> str:
        """Dedup key for daily snapshots (one JSON per physical broker account)."""
        return self.account_group or self.snapshot_subdir or self.workflow_id

    @property
    def api_key_env(self) -> str:
        return f"{self.env_prefix}_API_KEY"

    @property
    def secret_key_env(self) -> str:
        return f"{self.env_prefix}_SECRET_KEY"

    @property
    def account_id_env(self) -> str:
        return f"{self.env_prefix}_ACCOUNT_ID"


def _parse_entry(workflow_id: str, raw: Dict[str, Any]) -> WorkflowAccount:
    snap = str(raw.get("snapshot_subdir") or workflow_id.replace("-", "_"))
    return WorkflowAccount(
        workflow_id=workflow_id,
        broker=str(raw.get("broker") or "alpaca").lower(),
        env_prefix=str(raw.get("env_prefix") or workflow_id.upper().replace("-", "_")),
        snapshot_subdir=snap,
        data_dir=str(raw.get("data_dir") or f"data/{workflow_id.replace('-', '_')}"),
        account_group=str(raw.get("account_group") or snap),
        enabled=bool(raw.get("enabled", True)),
        label=str(raw.get("label") or workflow_id),
    )


def load_workflow_registry(path: Optional[Path] = None) -> Dict[str, WorkflowAccount]:
    path = path or _REGISTRY_PATH
    if not path.is_file():
        logger.warning("workflow_accounts.yaml missing", path=str(path))
        return {
            "weekly-scan": WorkflowAccount(
                "weekly-scan", "alpaca", "ALPACA", "stock", "data/performance", True, "Equity"
            ),
            "biotech-catalyst": WorkflowAccount(
                "biotech-catalyst",
                "alpaca",
                "BIOTECH_ALPACA",
                "biotech",
                "data/biotech",
                True,
                "Biotech",
            ),
        }
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    workflows = data.get("workflows") or {}
    return {wid: _parse_entry(wid, cfg) for wid, cfg in workflows.items() if isinstance(cfg, dict)}


def get_workflow(workflow_id: str) -> Optional[WorkflowAccount]:
    return load_workflow_registry().get(workflow_id)


def list_workflows(*, enabled_only: bool = False) -> List[WorkflowAccount]:
    reg = load_workflow_registry()
    items = list(reg.values())
    if enabled_only:
        items = [w for w in items if w.enabled]
    return sorted(items, key=lambda w: w.workflow_id)


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _alpaca_secret_env_names(prefix: str) -> tuple[str, ...]:
    """Accept {PREFIX}_API_SECRET_KEY (GitHub naming) or {PREFIX}_SECRET_KEY (legacy)."""
    return (f"{prefix}_API_SECRET_KEY", f"{prefix}_SECRET_KEY")


def _get_alpaca_secret(prefix: str) -> str:
    for name in _alpaca_secret_env_names(prefix):
        val = _env(name)
        if val:
            return val
    return ""


def resolve_alpaca_env_prefix(workflow: WorkflowAccount) -> Optional[str]:
    """Return env prefix that has both API key and secret set."""
    if workflow.broker != "alpaca":
        return None
    candidates = [workflow.env_prefix]
    if workflow.env_prefix == "MULTI_SLEEVE_ALPACA":
        candidates = list(_MULTI_SLEEVE_ALPACA_FALLBACK_PREFIXES)
    for prefix in candidates:
        if _env(f"{prefix}_API_KEY") and _get_alpaca_secret(prefix):
            return prefix
    return None


def workflow_credentials_configured(workflow: WorkflowAccount) -> bool:
    if workflow.broker == "alpaca":
        return resolve_alpaca_env_prefix(workflow) is not None
    if workflow.broker == "ibkr":
        acct = _env(workflow.account_id_env)
        host = _env("IBKR_GATEWAY_HOST") or _env("IBKR_HOST")
        return bool(acct and host)
    return False


def resolve_snapshot_subdir(account_or_workflow: str) -> str:
    """Map legacy names (stock/biotech) or workflow_id to snapshot subdir."""
    legacy = {"stock": "stock", "biotech": "biotech"}
    if account_or_workflow in legacy:
        return legacy[account_or_workflow]
    wf = get_workflow(account_or_workflow)
    if wf:
        return wf.snapshot_subdir
    return account_or_workflow.replace("-", "_")


def get_alpaca_credentials(workflow: WorkflowAccount) -> tuple[str, str]:
    prefix = resolve_alpaca_env_prefix(workflow)
    if not prefix:
        raise RuntimeError(
            f"Missing Alpaca keys for {workflow.workflow_id} "
            f"(set MULTI_SLEEVE_ALPACA_* or HEDGE_ALPACA_* for shared satellite account)"
        )
    secret = _get_alpaca_secret(prefix)
    if not secret:
        raise RuntimeError(f"Missing secret for prefix {prefix}")
    return _env(f"{prefix}_API_KEY"), secret


def list_physical_accounts(*, enabled_only: bool = True) -> List[WorkflowAccount]:
    """One representative workflow per physical account (for daily snapshots)."""
    seen: set[str] = set()
    out: List[WorkflowAccount] = []
    for wf in list_workflows(enabled_only=enabled_only):
        key = wf.physical_account_key
        if key in seen:
            continue
        if not workflow_credentials_configured(wf):
            continue
        seen.add(key)
        out.append(wf)
    return out


def get_broker(workflow_id: str) -> Any:
    """Return AlpacaBroker or IBKRBroker for workflow_id."""
    wf = get_workflow(workflow_id)
    if wf is None:
        raise KeyError(f"Unknown workflow: {workflow_id}")
    if wf.broker == "alpaca":
        from src.broker.alpaca import AlpacaBroker

        key, sec = get_alpaca_credentials(wf)
        return AlpacaBroker(api_key=key, secret_key=sec)
    if wf.broker == "ibkr":
        from src.broker.ibkr import IBKRBroker

        return IBKRBroker(workflow=wf)
    raise ValueError(f"Unsupported broker {wf.broker} for {workflow_id}")


def try_get_broker(workflow_id: str) -> Optional[Any]:
    wf = get_workflow(workflow_id)
    if wf is None or not wf.enabled:
        return None
    if not workflow_credentials_configured(wf):
        return None
    try:
        return get_broker(workflow_id)
    except Exception as e:
        logger.warning("Broker init failed", workflow=workflow_id, error=str(e))
        return None
