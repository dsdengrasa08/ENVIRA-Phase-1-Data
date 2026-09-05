"""Deterministic dependency, model, and execution-environment provenance."""

from __future__ import annotations

import hashlib
from importlib.metadata import distributions
import json
import platform
from pathlib import Path
from typing import Any

from .security import resolve_artifact_path, sha256_file

MODEL_MANIFEST_SCHEMA_VERSION = 1


def installed_distribution_inventory() -> list[dict[str, str]]:
    rows = [
        {
            "name": str(dist.metadata.get("Name") or "unknown"),
            "version": str(dist.version),
        }
        for dist in distributions()
    ]
    return sorted(rows, key=lambda row: (row["name"].casefold(), row["version"]))


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_model_manifest(root: Path, manifest_path: Path) -> dict[str, Any]:
    """Verify an approved model inventory using confined paths and streaming hashes."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("model_manifest_schema_version") != MODEL_MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported model manifest schema")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("model manifest must contain files")
    seen = set()
    verified = []
    for item in files:
        relative = item.get("path")
        if relative in seen:
            raise ValueError("duplicate model manifest path")
        seen.add(relative)
        path = resolve_artifact_path(root, relative)
        if path.stat().st_size != item.get("bytes"):
            raise ValueError(f"model size mismatch: {relative}")
        digest = sha256_file(path)
        if digest != item.get("sha256"):
            raise ValueError(f"model hash mismatch: {relative}")
        verified.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest})
    return {
        "valid": True,
        "backend": manifest.get("backend"),
        "backend_version": manifest.get("backend_version"),
        "model_set": manifest.get("model_set"),
        "files": verified,
        "model_manifest_sha256": sha256_file(manifest_path),
        "model_file_set_sha256": canonical_sha256(verified),
    }


def environment_fingerprint(
    *, config_sha256: str, model: dict[str, Any] | None, capabilities: dict[str, Any]
) -> dict[str, Any]:
    inventory = installed_distribution_inventory()
    value = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "dependencies": inventory,
        "dependency_inventory_sha256": canonical_sha256(inventory),
        "effective_config_sha256": config_sha256,
        "model_manifest_sha256": (model or {}).get("model_manifest_sha256"),
        "model_file_set_sha256": (model or {}).get("model_file_set_sha256"),
        "backend_capabilities": capabilities,
    }
    return {**value, "environment_sha256": canonical_sha256(value)}
