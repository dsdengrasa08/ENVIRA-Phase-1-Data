import hashlib
import json

import pytest

from envira_pdf_layout.artifact_validation import validate_exported_artifacts
from envira_pdf_layout.config import SecurityConfig
from envira_pdf_layout.security import (
    ArtifactSecurityError,
    redact_secrets,
    resolve_artifact_path,
    sha256_file,
)


@pytest.mark.parametrize(
    "value",
    ["../outside", "/etc/passwd", "C:\\Windows\\win.ini", "folder/../outside", ""],
)
def test_manifest_paths_reject_traversal_absolute_and_windows_paths(tmp_path, value):
    with pytest.raises((ArtifactSecurityError, FileNotFoundError)):
        resolve_artifact_path(tmp_path, value)


def test_manifest_path_rejects_symlink_escape(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    (tmp_path / "link").symlink_to(outside)
    with pytest.raises(ArtifactSecurityError, match="symlink"):
        resolve_artifact_path(tmp_path, "link")


def test_streaming_hash_enforces_size_limit(tmp_path):
    path = tmp_path / "large"
    path.write_bytes(b"0123456789")
    assert sha256_file(path) == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ArtifactSecurityError, match="too_large"):
        sha256_file(path, max_bytes=9)


def test_secret_and_uri_credentials_are_redacted():
    value = redact_secrets(
        {"PHASE1_API_TOKEN": "top-secret", "endpoint": "https://user:pass@example.test/x"}
    )
    assert value["PHASE1_API_TOKEN"] == "<redacted>"
    assert "user:pass" not in value["endpoint"]


def test_validator_rejects_unsafe_manifest_before_reading_outside(tmp_path):
    outside = tmp_path.parent / "outside-secret"
    outside.write_text("do not read", encoding="utf-8")
    required = {
        "effective_config.json": "{}",
        "pipeline_diagnostics.json": "{}",
        "page_records.jsonl": "",
        "physical_layout_regions.jsonl": "",
        "top_level_layout_regions.jsonl": "",
        "nested_layout_regions.jsonl": "",
        "layout_relationships.jsonl": "",
        "stage_trace.jsonl": "",
        "page_diagnostics.jsonl": "",
        "figure_completion_proposals.jsonl": "",
    }
    for name, content in required.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "files": [{"path": "../outside-secret", "bytes": outside.stat().st_size, "sha256": "0" * 64}],
    }
    (tmp_path / "artifact_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_exported_artifacts(tmp_path)
    assert not result["valid"]
    assert any(error["error"] == "unsafe_manifest_path" for error in result["errors"])


def test_validator_bounds_jsonl_lines(tmp_path):
    (tmp_path / "effective_config.json").write_text("{}")
    (tmp_path / "pipeline_diagnostics.json").write_text("{}")
    (tmp_path / "page_records.jsonl").write_text(json.dumps({"value": "x" * 100}) + "\n")
    result = validate_exported_artifacts(
        tmp_path, SecurityConfig(max_jsonl_line_bytes=20)
    )
    assert any("jsonl_line_limit" in error.get("detail", "") for error in result["errors"])
