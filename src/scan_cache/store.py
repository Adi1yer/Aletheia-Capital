"""
Persist market scan runs for TTM / historical analysis and weekly email past-performance.

Cache policy:
- A "weekly run" is one full scan identified by run_id and run_date (YYYY-MM-DD).
- We store only outputs needed for analysis: run metadata, tickers, signals, decisions,
  execution results, portfolio snapshots, and a compact data_snapshot (no raw HTML).
- Auto-prune is off by default (scan_cache_keep_weeks=0): all runs are retained locally.
- The weekly email "past performance" section uses this canonical structure:
  list_runs() then load_run() to read meta, portfolio_after/portfolio_before, execution_results.
- `src/backtesting/agent_evaluator.py` and `src/backtesting/learning_outcomes.py` read consecutive
  runs to score agents and to inject per-(agent,ticker) calibration into future prompts.
"""

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.config.settings import settings

logger = structlog.get_logger()


def _json_serial(obj: Any) -> Any:
    """Convert numpy and other non-JSON types for serialization."""
    if hasattr(obj, "item"):
        return obj.item()
    if hasattr(obj, "tolist"):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _safe_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively convert dict values to JSON-serializable types."""
    out = {}
    for k, v in d.items():
        if v is None or isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif hasattr(v, "model_dump"):
            out[k] = v.model_dump() if hasattr(v, "model_dump") else dict(v)
        elif hasattr(v, "item"):
            out[k] = v.item()
        elif hasattr(v, "tolist"):
            out[k] = v.tolist()
        elif isinstance(v, dict):
            out[k] = _safe_dict(v)
        elif isinstance(v, (list, tuple)):
            out[k] = [_safe_dict(x) if isinstance(x, dict) else _json_serial(x) if hasattr(x, "item") else x for x in v]
        else:
            try:
                json.dumps(v, default=_json_serial)
                out[k] = v
            except TypeError:
                out[k] = str(v)
    return out


class ScanCache:
    """
    Cache weekly scan runs to local storage (canonical structure for past-performance and TTM).

    Each run is stored under <base_dir>/<run_id>/ with only needed outputs:
    - meta.json (run_id, run_date, config, tickers, start/end date, duration)
    - signals.json (agent signals)
    - decisions.json (portfolio decisions)
    - risk.json (risk analysis)
    - portfolio_before.json / portfolio_after.json
    - data_snapshot.json (per-ticker: prices summary, metrics, line items, news titles; no raw HTML)
    - execution_results.json (if execute=True)
    """

    def __init__(self, base_dir: Optional[str] = None):
        """Initialize scan cache at configured base directory.

        If base_dir is not provided, we use settings.scan_cache_dir.
        """
        effective_dir = base_dir or getattr(settings, "scan_cache_dir", "data/scan_cache")
        self.base_dir = Path(effective_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Scan cache initialized", base_dir=str(self.base_dir))

    def save_run(
        self,
        run_id: str,
        run_date: str,
        config: Dict[str, Any],
        tickers: List[str],
        start_date: str,
        end_date: str,
        data_snapshot: Dict[str, Any],
        agent_signals: Dict[str, Dict[str, Any]],
        risk_analysis: Dict[str, Any],
        decisions: Dict[str, Any],
        portfolio_before: Optional[Dict[str, Any]] = None,
        portfolio_after: Optional[Dict[str, Any]] = None,
        execution_results: Optional[Dict[str, Any]] = None,
        duration_seconds: Optional[float] = None,
    ) -> str:
        """
        Persist a full scan run. Returns the path to the run directory.
        """
        run_path = self.base_dir / run_id
        run_path.mkdir(parents=True, exist_ok=True)

        meta = {
            "run_id": run_id,
            "run_date": run_date,
            "config": config,
            "ticker_count": len(tickers),
            "tickers": tickers,
            "start_date": start_date,
            "end_date": end_date,
            "duration_seconds": duration_seconds,
            "saved_at": datetime.now().isoformat(),
        }
        _write_json(run_path / "meta.json", meta)

        _write_json(run_path / "signals.json", _safe_dict(agent_signals))
        _write_json(run_path / "decisions.json", _safe_dict(decisions))
        _write_json(run_path / "risk.json", _safe_dict(risk_analysis))
        _write_json(run_path / "data_snapshot.json", _safe_dict(data_snapshot))

        if portfolio_before is not None:
            _write_json(run_path / "portfolio_before.json", _safe_dict(portfolio_before))
        if portfolio_after is not None:
            _write_json(run_path / "portfolio_after.json", _safe_dict(portfolio_after))
        if execution_results is not None:
            _write_json(run_path / "execution_results.json", _safe_dict(execution_results))

        logger.info(
            "Scan run cached",
            run_id=run_id,
            run_date=run_date,
            ticker_count=len(tickers),
            path=str(run_path),
        )
        return str(run_path)

    def load_run(self, run_id: str) -> Dict[str, Any]:
        """Load a single run by run_id. Returns dict with meta, signals, decisions, risk, data_snapshot, etc."""
        run_path = self.base_dir / run_id
        if not run_path.is_dir():
            raise FileNotFoundError(f"Run not found: {run_id}")

        out = {}
        for name, filename in [
            ("meta", "meta.json"),
            ("signals", "signals.json"),
            ("decisions", "decisions.json"),
            ("risk", "risk.json"),
            ("data_snapshot", "data_snapshot.json"),
            ("portfolio_before", "portfolio_before.json"),
            ("portfolio_after", "portfolio_after.json"),
            ("execution_results", "execution_results.json"),
        ]:
            p = run_path / filename
            if p.exists():
                out[name] = _read_json(p)
        return out

    def list_runs(
        self,
        limit: Optional[int] = None,
        since_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List cached runs (newest first by run_date/saved_at). Each item has run_id, run_date, ticker_count from meta.
        Optionally limit count and/or filter since_date (YYYY-MM-DD).
        """
        if not self.base_dir.exists():
            return []

        runs = []
        for path in self.base_dir.iterdir():
            if not path.is_dir():
                continue
            meta_file = path / "meta.json"
            if not meta_file.exists():
                continue
            try:
                meta = _read_json(meta_file)
                run_date = meta.get("run_date") or (meta.get("saved_at") or "")[:10]
                if since_date and run_date < since_date:
                    continue
                runs.append({
                    "run_id": path.name,
                    "run_date": run_date,
                    "ticker_count": meta.get("ticker_count", 0),
                    "saved_at": meta.get("saved_at"),
                })
            except Exception as e:
                logger.warning("Could not read run meta", path=str(meta_file), error=str(e))
                continue
        runs.sort(key=lambda r: (r.get("run_date") or "", r.get("saved_at") or ""), reverse=True)
        if limit:
            runs = runs[:limit]
        return runs

    def prune_old_runs(self, keep_weeks: int = 12) -> int:
        """
        Delete run directories older than keep_weeks (by run_date or saved_at).
        Returns the number of run directories removed.
        """
        if keep_weeks <= 0:
            return 0
        cutoff = (datetime.now() - timedelta(weeks=keep_weeks)).strftime("%Y-%m-%d")
        removed = 0
        for path in list(self.base_dir.iterdir()):
            if not path.is_dir():
                continue
            meta_file = path / "meta.json"
            if not meta_file.exists():
                continue
            try:
                meta = _read_json(meta_file)
                run_date = meta.get("run_date") or (meta.get("saved_at") or "")[:10]
                if run_date < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
                    removed += 1
                    logger.info("Pruned old run", run_id=path.name, run_date=run_date)
            except Exception as e:
                logger.warning("Could not read run meta for prune", path=str(meta_file), error=str(e))
        if removed:
            logger.info("Prune complete", removed=removed, keep_weeks=keep_weeks)
        return removed


def _write_json(path: Path, data: Any) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=_json_serial)


def _read_json(path: Path) -> Any:
    with open(path) as f:
        return json.load(f)
