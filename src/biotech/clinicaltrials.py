"""ClinicalTrials.gov API v2 — study search by free text (company name)."""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import quote

import structlog

from src.biotech.http_cache import cached_get_json
from src.biotech.models import TrialSummary

logger = structlog.get_logger()

# Legal-entity suffixes that over-constrain the ClinicalTrials.gov free-text query
# (e.g. "Alnylam Pharmaceuticals, Inc." returns 3 hits vs 96 without the suffix).
_LEGAL_SUFFIX_RE = re.compile(
    r"[,\.]?\s+(inc|incorporated|corp|corporation|ltd|limited|llc|l\.l\.c|plc|"
    r"n\.v|s\.a|a\.g|ag|se|co|company|holdings|group|sa|nv)\.?$",
    re.IGNORECASE,
)


def clean_company_term(name: str) -> str:
    """Strip commas and trailing legal-entity suffixes to broaden trial search."""
    term = (name or "").strip()
    term = term.replace(",", " ")
    prev = None
    while prev != term:
        prev = term
        term = _LEGAL_SUFFIX_RE.sub("", term).strip()
    return re.sub(r"\s+", " ", term).strip() or (name or "").strip()


def _study_to_trial(s: dict) -> Optional[TrialSummary]:
    try:
        proto = s.get("protocolSection", {}) or {}
        id_block = proto.get("identificationModule", {}) or {}
        status_mod = proto.get("statusModule", {}) or {}
        cond_mod = proto.get("conditionsModule", {}) or {}
        design_mod = proto.get("designModule", {}) or {}
        sponsor = proto.get("sponsorCollaboratorsModule", {}) or {}
        nct = id_block.get("nctId", "")
        title = id_block.get("briefTitle", "") or id_block.get("officialTitle", "")
        status = status_mod.get("overallStatus", "")
        pcd = status_mod.get("primaryCompletionDateStruct") or {}
        ccd = status_mod.get("completionDateStruct") or {}
        primary_completion_date = ""
        completion_date = ""
        if isinstance(pcd, dict) and pcd.get("date"):
            primary_completion_date = str(pcd.get("date", "")).replace("Z", "")[:10]
        if isinstance(ccd, dict) and ccd.get("date"):
            completion_date = str(ccd.get("date", "")).replace("Z", "")[:10]
        # ClinicalTrials.gov API v2 exposes phases under designModule (not identificationModule).
        phases = design_mod.get("phases") or id_block.get("phases") or []
        phase = ",".join(phases) if isinstance(phases, list) else str(phases)
        conds = cond_mod.get("conditions", []) or []
        lead = sponsor.get("leadSponsor", {}) or {}
        sp_name = lead.get("name", "")
        return TrialSummary(
            nct_id=nct,
            title=title[:500],
            status=status,
            phase=phase,
            conditions=[str(c) for c in conds][:12],
            sponsor=sp_name,
            primary_completion_date=primary_completion_date,
            completion_date=completion_date,
            raw={},
        )
    except Exception:
        return None


def fetch_trial_by_nct_id(nct_id: str) -> Optional[TrialSummary]:
    """Fetch a single study by NCT ID."""
    nct = (nct_id or "").strip().upper()
    if not nct.startswith("NCT"):
        return None
    url = f"https://clinicaltrials.gov/api/v2/studies/{nct}?format=json"
    try:
        data = cached_get_json(url, ttl_seconds=12 * 3600)
    except Exception as e:
        logger.warning("ClinicalTrials NCT fetch failed", nct_id=nct, error=str(e))
        return None
    if isinstance(data, dict) and data.get("protocolSection"):
        return _study_to_trial(data)
    studies = data.get("studies") if isinstance(data, dict) else []
    if studies:
        return _study_to_trial(studies[0])
    return None


def search_trials_by_term(term: str, page_size: int = 60) -> List[TrialSummary]:
    """Search studies; `term` is typically company long name.

    A larger default page size is required so near-term readouts surface — the
    relevance-sorted default otherwise returns mostly old/far-future trials.
    """
    cleaned = clean_company_term(term)
    if not cleaned:
        return []
    q = quote(cleaned)
    url = f"https://clinicaltrials.gov/api/v2/studies?query.term={q}&pageSize={page_size}&format=json"
    try:
        data = cached_get_json(url, ttl_seconds=12 * 3600)
    except Exception as e:
        logger.warning("ClinicalTrials search failed", error=str(e))
        return []

    studies = data.get("studies") if isinstance(data, dict) else []
    out: List[TrialSummary] = []
    for s in studies or []:
        t = _study_to_trial(s)
        if t:
            out.append(t)
    return out
