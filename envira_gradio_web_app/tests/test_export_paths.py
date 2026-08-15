from pathlib import Path

import pytest

from envira_gradio.pipeline.export import _manifest_path
from envira_gradio.pipeline.artifact_validation import validate_exported_artifacts
from envira_gradio.pipeline.security import sha256_file


def test_overlay_manifest_path_preserves_subdirectory(tmp_path: Path):
    overlay = tmp_path / "overlays" / "page_0001_docling_layout_overlay.png"
    overlay.parent.mkdir()
    overlay.touch()

    assert _manifest_path(tmp_path, overlay) == (
        "overlays/page_0001_docling_layout_overlay.png"
    )


def test_manifest_path_rejects_files_outside_run_root(tmp_path: Path):
    outside = tmp_path.parent / "outside.png"
    with pytest.raises(ValueError):
        _manifest_path(tmp_path, outside)


def test_validator_resolves_nested_overlay_manifest_entry(tmp_path: Path):
    for name in ("effective_config.json", "pipeline_diagnostics.json"):
        (tmp_path / name).write_text("{}")
    for name in (
        "page_records.jsonl",
        "physical_layout_regions.jsonl",
        "top_level_layout_regions.jsonl",
        "nested_layout_regions.jsonl",
        "layout_relationships.jsonl",
        "stage_trace.jsonl",
        "page_diagnostics.jsonl",
        "figure_completion_proposals.jsonl",
    ):
        (tmp_path / name).write_text("")
    overlay = tmp_path / "overlays" / "page_0001_docling_layout_overlay.png"
    overlay.parent.mkdir()
    overlay.write_bytes(b"overlay")
    manifest = {
        "schema_version": 1,
        "files": [
            {
                "path": _manifest_path(tmp_path, overlay),
                "bytes": overlay.stat().st_size,
                "sha256": sha256_file(overlay),
            }
        ],
    }
    import json

    (tmp_path / "artifact_manifest.json").write_text(json.dumps(manifest))

    assert validate_exported_artifacts(tmp_path)["valid"] is True
