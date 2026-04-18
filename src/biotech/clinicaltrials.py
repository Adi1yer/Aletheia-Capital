"""ClinicalTrials.gov API v2 — study search by free text (company name)."""

from __future__ import annotations

from typing import List
from urllib.parse import quote

import structlog

from src.biotech.http_cache import cached_get_json
from src.biotech.models import TrialSummary

logger = structlog.get_logger()


def search_trials_by_term(term: str, page_size: int = 15) -> List[TrialSummary]:
    """Search studies; `term` is typically company long name."""
    if not term.strip():
        return []
    q = quote(term.strip())
    url = f"https://clinicaltrials.gov/api/v2/studies?query.term={q}&pageSize={page_size}&format=json"
    try:
        data = cached_get_json(url, ttl_seconds=12 * 3600)
    except Exception as e:
        logger.warning("ClinicalTrials search failed", error=str(e))
        return []

    studies = data.get("studies") if isinstance(data, dict) else []
    out: List[TrialSummary] = []
    for s in studies or []:
        try:
            proto = s.get("protocolSection", {}) or {}
            id_block = proto.get("identificationModule", {}) or {}
            status_mod = proto.get("statusModule", {}) or {}
            desc = proto.get("descriptionModule", {}) or {}
            cond_mod = proto.get("conditionsModule", {}) or {}
            sponsor = proto.get("sponsorCollaboratorsModule", {}) or {}
            nct = id_block.get("nctId", "")
            title = id_block.get("briefTitle", "") or id_block.get("officialTitle", "")
            status = status_mod.get("overallStatus", "")
            phases = id_block.get("phases") or []
            phase = ",".join(phases) if isinstance(phases, list) else str(phases)
            conds = cond_mod.get("conditions", []) or []
            lead = sponsor.get("leadSponsor", {}) or {}
            sp_name = lead.get("name", "")
            out.append(
                TrialSummary(
                    nct_id=nct,
                    title=title[:500],
                    status=status,
                    phase=phase,
                    conditions=[str(c) for c in conds][:12],
                    sponsor=sp_name,
                    # Omit full protocol JSON — it explodes token count; structured fields above suffice.
                    raw={},
                )
            )
        except Exception:
            continue
    return out
