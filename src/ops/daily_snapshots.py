"""Persist and load daily Alpaca snapshots for main vs biotech paper accounts."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Literal, Set, Tuple

from src.config.settings import settings

Account = Literal["stock", "biotech"]


def _root() -> Path:
    return Path(getattr(settings, "daily_snapshots_dir", "data/daily_snapshots"))


def snapshot_path(account: Account, day: date | None = None) -> Path:
    day = day or date.today()
    sub = "stock" if account == "stock" else "biotech"
    return _root() / sub / f"{day.isoformat()}.json"


def save_snapshot(account: Account, payload: Dict[str, Any]) -> Path:
    """Write one JSON file per day (overwrites same day)."""
    path = snapshot_path(account)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return path


def _option_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = payload.get("option_positions") or []
    return [x for x in rows if isinstance(x, dict)]


def _option_symbol_set(payload: Dict[str, Any]) -> Set[str]:
    return {str(x.get("symbol", "")).strip() for x in _option_rows(payload) if x.get("symbol")}


def _straddle_summaries_from_rows(rows: List[Dict[str, Any]]) -> List[str]:
    """Group long call+put same underlying/expiry/strike into one line each."""
    buckets: Dict[Tuple[str, str, float], Dict[str, str]] = {}
    for o in rows:
        u = str(o.get("underlying") or "").strip().upper()
        exp = str(o.get("expiry") or "").strip()
        typ = str(o.get("type") or "").lower()
        sym = str(o.get("symbol") or "").strip()
        if not u or not exp or typ not in ("call", "put") or not sym:
            continue
        try:
            k = float(o.get("strike") or 0)
        except (TypeError, ValueError):
            k = 0.0
        key = (u, exp, k)
        buckets.setdefault(key, {})[typ] = sym
    out: List[str] = []
    for (u, exp, k), legs in sorted(buckets.items()):
        if "call" in legs and "put" in legs:
            out.append(f"{u} {exp} @{k:g} (straddle {legs['call']} + {legs['put']})")
    return out


def _symbols_in_straddles(rows: List[Dict[str, Any]]) -> Set[str]:
    """OCC symbols that are part of a full call+put pair (same U/exp/strike)."""
    buckets: Dict[Tuple[str, str, float], Dict[str, str]] = {}
    for o in rows:
        u = str(o.get("underlying") or "").strip().upper()
        exp = str(o.get("expiry") or "").strip()
        typ = str(o.get("type") or "").lower()
        sym = str(o.get("symbol") or "").strip()
        if not u or not exp or typ not in ("call", "put") or not sym:
            continue
        try:
            k = float(o.get("strike") or 0)
        except (TypeError, ValueError):
            k = 0.0
        buckets.setdefault((u, exp, k), {})[typ] = sym
    out: Set[str] = set()
    for legs in buckets.values():
        if "call" in legs and "put" in legs:
            out.add(legs["call"])
            out.add(legs["put"])
    return out


def _lifecycle_delta_dict(prior: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    prev_syms = _option_symbol_set(prior)
    cur_syms = _option_symbol_set(current)
    opened = sorted(cur_syms - prev_syms)
    closed = sorted(prev_syms - cur_syms)
    carried = sorted(cur_syms & prev_syms)
    notes: List[str] = []
    if opened:
        o_rows = [r for r in _option_rows(current) if str(r.get("symbol", "")) in opened]
        straddles = _straddle_summaries_from_rows(o_rows)
        paired_syms = _symbols_in_straddles(o_rows)
        if straddles:
            notes.append("Opened (straddle groups): " + "; ".join(straddles))
        loose = sorted(set(opened) - paired_syms)
        if loose:
            notes.append("Opened legs (outside straddle pairs): " + ", ".join(loose[:20]))
            if len(loose) > 20:
                notes.append(f"... and {len(loose) - 20} more opened symbols")
    if closed:
        notes.append("Closed / reduced legs (no longer in book): " + ", ".join(closed[:20]))
        if len(closed) > 20:
            notes.append(f"... and {len(closed) - 20} more closed symbols")
    if carried and not opened and not closed:
        notes.append(f"Carried {len(carried)} option leg(s) unchanged vs prior day")
    elif carried and (opened or closed):
        notes.append(f"Also carried unchanged: {len(carried)} option leg(s) vs prior day")
    if not notes:
        if not prev_syms and not cur_syms:
            notes.append("No option positions in either snapshot day")
        else:
            notes.append("Option book unchanged (same set of OCC symbols)")
    return {
        "prior_date": prior.get("date"),
        "opened_option_symbols": opened,
        "closed_option_symbols": closed,
        "carried_option_symbols": carried,
        "notes": notes,
    }


def enrich_payload_with_prior_day_lifecycle(account: Account, payload: Dict[str, Any]) -> None:
    """Mutate payload with option-book delta vs prior calendar day (if JSON exists)."""
    day_raw = payload.get("date")
    try:
        d = date.fromisoformat(str(day_raw)) if day_raw else date.today()
    except ValueError:
        d = date.today()
    prior_d = d - timedelta(days=1)
    prior_path = snapshot_path(account, prior_d)
    if not prior_path.is_file():
        payload["position_lifecycle_vs_prior_day"] = {
            "prior_date": prior_d.isoformat(),
            "prior_snapshot_found": False,
            "notes": [
                "No prior-day snapshot file; run daily_health_check on consecutive days for deltas."
            ],
        }
        return
    try:
        with open(prior_path) as f:
            prior = json.load(f)
    except Exception:
        payload["position_lifecycle_vs_prior_day"] = {
            "prior_date": prior_d.isoformat(),
            "prior_snapshot_found": False,
            "notes": ["Prior-day file unreadable."],
        }
        return
    delta = _lifecycle_delta_dict(prior, payload)
    delta["prior_snapshot_found"] = True
    payload["position_lifecycle_vs_prior_day"] = delta


def _underlying_lifecycle_states(oldest: Dict[str, Any], newest: Dict[str, Any]) -> Dict[str, str]:
    """Map underlying ticker -> one-sentence lifecycle vs start of window."""

    def syms_for_u(rows: List[Dict[str, Any]], u: str) -> Set[str]:
        u = u.upper()
        return {
            str(r.get("symbol", "")).strip()
            for r in rows
            if str(r.get("underlying", "")).strip().upper() == u and r.get("symbol")
        }

    old_rows = _option_rows(oldest)
    new_rows = _option_rows(newest)
    underlyings: Set[str] = set()
    for r in old_rows + new_rows:
        x = str(r.get("underlying", "")).strip().upper()
        if x:
            underlyings.add(x)
    out: Dict[str, str] = {}
    for u in sorted(underlyings):
        so, sn = syms_for_u(old_rows, u), syms_for_u(new_rows, u)
        if not so and sn:
            nu = [r for r in new_rows if str(r.get("underlying", "")).strip().upper() == u]
            st = _straddle_summaries_from_rows(nu)
            if st:
                out[u] = (
                    "Position lifecycle: new option exposure this week vs start of window — "
                    + "; ".join(st)
                    + "."
                )
            else:
                out[u] = (
                    "Position lifecycle: new option leg(s) appeared this week vs start of window "
                    f"({len(sn)} contract(s))."
                )
        elif so and not sn:
            out[u] = (
                "Position lifecycle: option exposure on this name was fully closed or rolled away "
                "during the snapshot window vs the oldest day on file."
            )
        elif so and sn and so == sn:
            out[u] = (
                "Position lifecycle: carried the same option contract(s) across the window "
                f"({len(sn)} leg(s)); book unchanged at contract-symbol level."
            )
        elif so and sn:
            out[u] = (
                "Position lifecycle: adjusted book this week — contracts changed vs oldest day "
                f"(was {len(so)} leg(s), now {len(sn)}); possible roll/add/trim."
            )
        else:
            out[
                u
            ] = "Position lifecycle: no option legs recorded for this underlying in the window."
    return out


def load_snapshots_for_days(
    account: Account, days: int = 7, end: date | None = None
) -> List[Dict[str, Any]]:
    """Load up to `days` daily files ending at `end`, newest first."""
    end = end or date.today()
    out: List[Dict[str, Any]] = []
    for i in range(days):
        d = end - timedelta(days=i)
        p = snapshot_path(account, d)
        if not p.is_file():
            continue
        try:
            with open(p) as f:
                out.append(json.load(f))
        except Exception:
            continue
    return out


def format_week_position_lifecycle_markdown(
    account: Account, days: int = 7
) -> Tuple[str, Dict[str, str]]:
    """
    Week-over-week option lifecycle for prompts/email: daily deltas + span summary.
    Returns (markdown_block, per_underlying_one_liner) for tying to tickers.
    """
    rows = load_snapshots_for_days(account, days=days)
    if not rows:
        return "", {}
    newest, oldest = rows[0], rows[-1]
    label = "Main paper" if account == "stock" else "Biotech paper"
    lines: List[str] = [
        f"### {label} — position lifecycle (option book)",
        "",
        "Use this for **information only**: what opened, carried, or closed during the week.",
        "",
    ]
    # Daily deltas (newest first in rows)
    for r in rows:
        day = r.get("date", "?")
        lc = r.get("position_lifecycle_vs_prior_day")
        if not lc:
            lines.append(
                f"- **{day}**: (no `position_lifecycle_vs_prior_day` yet — run daily_health_check to record deltas)"
            )
            continue
        if lc.get("prior_snapshot_found") is False:
            msg = " | ".join(str(x) for x in (lc.get("notes") or [])[:2])
            lines.append(f"- **{day}**: {msg or 'no prior-day snapshot; gap or first day'}")
            continue
        n = lc.get("notes") or []
        if n:
            lines.append(f"- **{day}** vs prior: " + " | ".join(str(x) for x in n[:3]))
        else:
            lines.append(f"- **{day}**: (no lifecycle notes)")
    lines.append("")

    per_u: Dict[str, str] = {}
    if len(rows) >= 2:
        o_syms, n_syms = _option_symbol_set(oldest), _option_symbol_set(newest)
        opened_w = sorted(n_syms - o_syms)
        closed_w = sorted(o_syms - n_syms)
        carried_w = sorted(n_syms & o_syms)
        lines.append(
            f"**Window span ({oldest.get('date')} → {newest.get('date')})**: "
            f"opened {len(opened_w)} leg(s), closed {len(closed_w)} leg(s), "
            f"carried unchanged {len(carried_w)} leg(s) (by OCC symbol)."
        )
        if opened_w:
            o_rows = [x for x in _option_rows(newest) if str(x.get("symbol", "")) in opened_w]
            st = _straddle_summaries_from_rows(o_rows)
            if st:
                lines.append("- New straddle groups this week: " + "; ".join(st))
        lines.append("")
        per_u = _underlying_lifecycle_states(oldest, newest)
    else:
        lines.append(
            "*Only one daily snapshot in range; week-over-week span summary needs ≥2 days.*"
        )
        lines.append("")
    body = "\n".join(lines).strip()
    return body, per_u


def format_snapshots_markdown(account: Account, days: int = 7) -> str:
    """Human-readable block for prompts and email from the last N snapshots."""
    rows = load_snapshots_for_days(account, days=days)
    if not rows:
        return ""
    label = "Main paper account" if account == "stock" else "Biotech paper account"
    lines = [f"### {label} — last {len(rows)} daily snapshot(s) (newest first)", ""]
    for r in rows:
        day = r.get("date", "?")
        eq = r.get("equity")
        cash = r.get("cash")
        npos = r.get("position_count", 0)
        if isinstance(eq, (int, float)) and isinstance(cash, (int, float)):
            lines.append(f"- **{day}**: equity ${eq:,.2f}, cash ${cash:,.2f}, positions {npos}")
        else:
            lines.append(f"- **{day}**: {r}")
        alerts = r.get("alerts") or []
        if alerts:
            lines.append(f"  - alerts: {', '.join(alerts)}")
        top = r.get("top_positions") or []
        if top:
            bits = [f"{x.get('symbol')} {x.get('pct_equity', 0):.1f}% eq" for x in top[:5]]
            lines.append(f"  - top: {', '.join(bits)}")
        opts = r.get("option_positions") or []
        lc = r.get("position_lifecycle_vs_prior_day")
        if isinstance(lc, dict) and lc.get("notes"):
            lines.append("  - vs prior day: " + " | ".join(str(x) for x in lc["notes"][:2]))
        if opts:
            # Group by (underlying, expiry) and summarize long call+put premium -> rough breakevens.
            grouped: Dict[tuple, List[Dict[str, Any]]] = {}
            for o in opts:
                key = (o.get("underlying"), o.get("expiry"))
                grouped.setdefault(key, []).append(o)
            for (u, exp), legs in list(grouped.items())[:3]:
                calls = [x for x in legs if x.get("type") == "call"]
                puts = [x for x in legs if x.get("type") == "put"]
                if not calls or not puts:
                    continue
                c = calls[0]
                p = puts[0]
                prem = float(c.get("avg_entry_price", 0) or 0) + float(
                    p.get("avg_entry_price", 0) or 0
                )
                k_call = float(c.get("strike", 0) or 0)
                k_put = float(p.get("strike", 0) or 0)
                if k_call > 0 and k_put > 0 and prem > 0:
                    lo = k_put - prem
                    hi = k_call + prem
                    lines.append(
                        f"  - options {u} {exp}: long straddle-ish; est b/e {lo:.2f} to {hi:.2f} (from avg premiums)"
                    )
        lines.append("")
    return "\n".join(lines).strip()
