import hashlib
import json

import pytest

from envira_pdf_layout.supply_chain import (
    environment_fingerprint,
    validate_model_manifest,
)


def manifest_for(root, content=b"weights"):
    model = root / "model.safetensors"
    model.write_bytes(content)
    manifest = root / "model-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "model_manifest_schema_version": 1,
                "backend": "docling",
                "backend_version": "2.119.0",
                "model_set": "test",
                "files": [
                    {
                        "path": model.name,
                        "bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return manifest, model


def test_model_manifest_verifies_files_and_produces_stable_digests(tmp_path):
    manifest, model = manifest_for(tmp_path)
    first = validate_model_manifest(tmp_path, manifest)
    second = validate_model_manifest(tmp_path, manifest)
    assert first == second
    assert first["valid"]
    model.write_bytes(b"changed")
    with pytest.raises(ValueError, match="size mismatch|hash mismatch"):
        validate_model_manifest(tmp_path, manifest)


def test_model_manifest_rejects_symlinks(tmp_path):
    outside = tmp_path.parent / "outside-model"
    outside.write_bytes(b"weights")
    link = tmp_path / "model.safetensors"
    link.symlink_to(outside)
    manifest = tmp_path / "model-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "model_manifest_schema_version": 1,
                "files": [{"path": link.name, "bytes": 7, "sha256": hashlib.sha256(b"weights").hexdigest()}],
            }
        )
    )
    with pytest.raises(ValueError, match="symlink"):
        validate_model_manifest(tmp_path, manifest)


def test_environment_fingerprint_is_deterministic(monkeypatch):
    monkeypatch.setattr(
        "envira_pdf_layout.supply_chain.installed_distribution_inventory",
        lambda: [{"name": "example", "version": "1.0"}],
    )
    first = environment_fingerprint(
        config_sha256="a" * 64, model=None, capabilities={"remote": False}
    )
    assert first == environment_fingerprint(
        config_sha256="a" * 64, model=None, capabilities={"remote": False}
    )
