"""Optional S3/R2 backup for scan_cache run directories."""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path
from typing import List, Optional

import structlog

logger = structlog.get_logger()


def _s3_client():
    try:
        import boto3
    except ImportError as e:
        raise RuntimeError("boto3 required for S3 scan cache; pip install boto3") from e

    endpoint = (os.getenv("AWS_ENDPOINT_URL") or os.getenv("SCAN_CACHE_S3_ENDPOINT") or "").strip()
    kwargs = {}
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client("s3", **kwargs)


def is_configured() -> bool:
    return bool((os.getenv("SCAN_CACHE_S3_BUCKET") or "").strip())


def _object_key(prefix: str, run_id: str) -> str:
    p = (prefix or "scan_cache").strip("/")
    return f"{p}/{run_id}.tar.gz"


def upload_run(run_id: str, base_dir: str = "data/scan_cache") -> bool:
    bucket = (os.getenv("SCAN_CACHE_S3_BUCKET") or "").strip()
    if not bucket:
        return False
    run_path = Path(base_dir) / run_id
    if not run_path.is_dir():
        logger.warning("S3 upload skip: run dir missing", run_id=run_id)
        return False
    prefix = (os.getenv("SCAN_CACHE_S3_PREFIX") or "scan_cache").strip()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(run_path, arcname=run_id)
    buf.seek(0)
    key = _object_key(prefix, run_id)
    try:
        client = _s3_client()
        client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
        logger.info("Uploaded scan run to S3", run_id=run_id, key=key)
        return True
    except Exception as e:
        logger.warning("S3 upload failed", run_id=run_id, error=str(e))
        return False


def restore_recent_runs(
    n: int = 26,
    base_dir: str = "data/scan_cache",
) -> int:
    """Download missing recent runs from S3. Returns count restored."""
    bucket = (os.getenv("SCAN_CACHE_S3_BUCKET") or "").strip()
    if not bucket:
        return 0
    prefix = (os.getenv("SCAN_CACHE_S3_PREFIX") or "scan_cache").strip()
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    try:
        client = _s3_client()
        resp = client.list_objects_v2(Bucket=bucket, Prefix=f"{prefix.strip('/')}/")
        keys = [o["Key"] for o in (resp.get("Contents") or []) if o["Key"].endswith(".tar.gz")]
        keys.sort(reverse=True)
        keys = keys[: max(1, int(n))]
        restored = 0
        for key in keys:
            run_id = Path(key).stem.replace(".tar", "")
            if (base / run_id).is_dir():
                continue
            obj = client.get_object(Bucket=bucket, Key=key)
            data = obj["Body"].read()
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                tar.extractall(path=base)
            restored += 1
            logger.info("Restored scan run from S3", run_id=run_id)
        return restored
    except Exception as e:
        logger.warning("S3 restore failed", error=str(e))
        return 0


def list_remote_run_ids(limit: int = 50) -> List[str]:
    bucket = (os.getenv("SCAN_CACHE_S3_BUCKET") or "").strip()
    if not bucket:
        return []
    prefix = (os.getenv("SCAN_CACHE_S3_PREFIX") or "scan_cache").strip()
    try:
        client = _s3_client()
        resp = client.list_objects_v2(Bucket=bucket, Prefix=f"{prefix.strip('/')}/", MaxKeys=limit)
        out = []
        for o in resp.get("Contents") or []:
            name = Path(o["Key"]).name.replace(".tar.gz", "")
            if name:
                out.append(name)
        return out
    except Exception:
        return []
