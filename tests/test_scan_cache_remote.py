"""Tests for optional S3/R2 scan_cache remote store."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.scan_cache import remote_store as rs


def test_is_configured_false_when_bucket_missing(monkeypatch):
    monkeypatch.delenv("SCAN_CACHE_S3_BUCKET", raising=False)
    assert rs.is_configured() is False


def test_upload_run_puts_tar_gz(monkeypatch, tmp_path: Path):
    run_id = "2026-05-19_abcd1234"
    run_dir = tmp_path / "data" / "scan_cache" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "meta.json").write_text('{"ok": true}')

    monkeypatch.setenv("SCAN_CACHE_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("SCAN_CACHE_S3_PREFIX", "scan_cache")

    mock_client = MagicMock()
    captured = {}

    def put_object(**kwargs):
        captured.update(kwargs)

    mock_client.put_object = put_object

    with patch.object(rs, "_s3_client", return_value=mock_client):
        ok = rs.upload_run(run_id, base_dir=str(tmp_path / "data" / "scan_cache"))

    assert ok is True
    assert captured["Bucket"] == "test-bucket"
    assert captured["Key"] == f"scan_cache/{run_id}.tar.gz"
    body = captured["Body"]
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tar:
        names = tar.getnames()
    assert run_id in names[0]


def test_restore_recent_runs_skips_existing(monkeypatch, tmp_path: Path):
    base = tmp_path / "data" / "scan_cache"
    base.mkdir(parents=True)
    existing = "2026-05-12_existing"
    (base / existing).mkdir()

    monkeypatch.setenv("SCAN_CACHE_S3_BUCKET", "test-bucket")
    monkeypatch.setenv("SCAN_CACHE_S3_PREFIX", "scan_cache")

    run_id = "2026-05-19_newrun"
    inner = tmp_path / "pkg" / run_id
    inner.mkdir(parents=True)
    (inner / "meta.json").write_text("{}")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(inner, arcname=run_id)
    payload = buf.getvalue()

    mock_client = MagicMock()
    mock_client.list_objects_v2.return_value = {
        "Contents": [
            {"Key": f"scan_cache/{existing}.tar.gz"},
            {"Key": f"scan_cache/{run_id}.tar.gz"},
        ]
    }

    def get_object(Bucket, Key):
        if Key.endswith(f"{run_id}.tar.gz"):
            return {"Body": MagicMock(read=lambda: payload)}
        raise AssertionError(f"unexpected key {Key}")

    mock_client.get_object = get_object

    with patch.object(rs, "_s3_client", return_value=mock_client):
        restored = rs.restore_recent_runs(n=5, base_dir=str(base))

    assert restored == 1
    assert (base / run_id / "meta.json").is_file()
