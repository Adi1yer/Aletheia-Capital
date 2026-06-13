"""Guard helpers for workflow scan entrypoints."""

from __future__ import annotations

import structlog

from src.broker.registry import get_workflow

logger = structlog.get_logger()


def skip_if_workflow_disabled(workflow_id: str) -> bool:
    """Return True when the workflow is disabled or missing (caller should exit 0)."""
    wf = get_workflow(workflow_id)
    if wf is None or not wf.enabled:
        logger.info("Workflow disabled in registry — skipping", workflow=workflow_id)
        return True
    return False
