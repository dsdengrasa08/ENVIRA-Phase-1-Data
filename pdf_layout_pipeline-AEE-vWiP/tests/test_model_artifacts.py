import hashlib
import json

import pytest

from envira_pdf_layout.config import DoclingConfig
from envira_pdf_layout.model_artifacts import _acquisition_lock, ensure_model_artifacts


def _write_manifest(root):
    model = root / "weights.bin"
    model.write_bytes(b"approved-model")
    manifest = {
        "model_manifest_schema_version": 1,
        "backend": "docling",
        "backend_version": "2.119.0",
        "model_set": "test",
        "files": [{
            "path": model.name,
            "bytes": model.stat().st_size,
            "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        }],
    }
    (root / "model-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_model_readiness_requires_verified_manifest(tmp_path):
    _write_manifest(tmp_path)
    result = ensure_model_artifacts(
        DoclingConfig(artifacts_dir=tmp_path, min_model_size_mb=0)
    )
    assert result["ready"] is True
    assert result["verification"]["model_set"] == "test"


def test_model_hash_mismatch_fails_closed(tmp_path):
    _write_manifest(tmp_path)
    (tmp_path / "weights.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="model (size|hash) mismatch"):
        ensure_model_artifacts(
            DoclingConfig(artifacts_dir=tmp_path, min_model_size_mb=0)
        )


def test_model_acquisition_lock_rejects_concurrent_writer(tmp_path):
    model_dir = tmp_path / "models"
    model_dir.mkdir()
    with _acquisition_lock(model_dir):
        with pytest.raises(RuntimeError, match="already in progress"):
            with _acquisition_lock(model_dir):
                pass
    assert not (tmp_path / "models.download.lock").exists()
