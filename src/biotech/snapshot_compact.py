"""Reduce biotech snapshot size before LLM calls (avoid context overflow)."""

from __future__ import annotations

import json

from src.biotech.models import BiotechSnapshot

# Rough budget: DeepSeek chat ~131k tokens; leave room for system prompt + output.
MAX_LLM_SNAPSHOT_CHARS = 95_000


def compact_snapshot_dict(snapshot: BiotechSnapshot) -> dict:
    """Strip nested API blobs and cap string lengths; safe for JSON serialization."""
    d = snapshot.model_dump()
    trials_out = []
    for t in d.get("trials") or []:
        if not isinstance(t, dict):
            continue
        trials_out.append(
            {
                "nct_id": str(t.get("nct_id") or "")[:40],
                "title": str(t.get("title") or "")[:500],
                "status": str(t.get("status") or "")[:120],
                "phase": str(t.get("phase") or "")[:120],
                "conditions": [str(c)[:120] for c in (t.get("conditions") or [])[:10]],
                "sponsor": str(t.get("sponsor") or "")[:200],
            }
        )
    d["trials"] = trials_out
    d["raw_notes"] = str(d.get("raw_notes") or "")[:4000]
    news = d.get("news_titles") or []
    d["news_titles"] = [str(x)[:240] for x in news[:18]]
    filings = d.get("filings") or []
    out_filings = []
    for f in filings[:12]:
        if isinstance(f, dict):
            out_filings.append(
                {
                    "form": str(f.get("form") or "")[:32],
                    "filed_at": str(f.get("filed_at") or "")[:32],
                    "url": str(f.get("url") or "")[:240],
                }
            )
    d["filings"] = out_filings
    d["company_name"] = str(d.get("company_name") or "")[:300]
    d["sector"] = str(d.get("sector") or "")[:120]
    d["industry"] = str(d.get("industry") or "")[:120]
    return d


def snapshot_json_for_llm(snapshot: BiotechSnapshot) -> str:
    """Serialize a compact snapshot, dropping trials until under the char budget."""
    d = compact_snapshot_dict(snapshot)
    trials = list(d.get("trials") or [])
    while trials:
        s = json.dumps({**d, "trials": trials}, default=str, indent=2)
        if len(s) <= MAX_LLM_SNAPSHOT_CHARS:
            return s
        trials = trials[:-1]
        if not trials:
            break
    d["trials"] = trials
    s = json.dumps(d, default=str, indent=2)
    if len(s) > MAX_LLM_SNAPSHOT_CHARS:
        return s[: MAX_LLM_SNAPSHOT_CHARS - 80] + "\n... [truncated for context limit]\n"
    return s
