import hashlib
import json
from types import SimpleNamespace
import pytest

from envira_pdf_layout.export import export_pipeline_result


def paths(root):
    names = {
        "raw_json": "raw.json",
        "raw_markdown": "raw.md",
        "effective_config_json": "config.json",
        "diagnostics_json": "pipeline_diagnostics.json",
        "page_records_jsonl": "pages.jsonl",
        "regions_jsonl": "regions.jsonl",
        "raw_regions_jsonl": "raw_regions.jsonl",
        "resolved_regions_jsonl": "resolved.jsonl",
        "physical_regions_jsonl": "physical_layout_regions.jsonl",
        "top_level_regions_jsonl": "top_level_layout_regions.jsonl",
        "nested_regions_jsonl": "nested_layout_regions.jsonl",
        "figure_completion_proposals_jsonl": "completion.jsonl",
        "caption_relationships_jsonl": "caption_relationships.jsonl",
        "caption_groups_jsonl": "caption_groups.jsonl",
        "layout_relationships_jsonl": "layout_relationships.jsonl",
        "resolution_decisions_jsonl": "decisions.jsonl",
        "suppressed_regions_jsonl": "suppressed.jsonl",
        "post_body_assets_jsonl": "post_assets.jsonl",
        "post_body_asset_regions_jsonl": "post_regions.jsonl",
        "logical_tables_jsonl": "tables.jsonl",
        "stage_trace_jsonl": "stage_trace.jsonl",
        "page_diagnostics_jsonl": "page_diagnostics.jsonl",
        "artifact_manifest_json": "artifact_manifest.json",
        "summary_csv": "summary.csv",
    }
    return SimpleNamespace(
        document_dir=root, **{key: root / value for key, value in names.items()}
    )


def run(root, status):
    artifacts = paths(root)
    page = {
        "page_number": 1,
        "counts": {},
        "page_image_path": "page.png",
    }
    empty_fields = {
        key: []
        for key in (
            "final_regions raw_regions resolved_regions physical_regions "
            "top_level_regions nested_regions caption_overlap_relationships "
            "caption_groups layout_relationships resolution_decisions "
            "suppressed_regions post_body_assets post_body_asset_regions "
            "logical_tables stage_trace"
        ).split()
    }
    return SimpleNamespace(
        document=SimpleNamespace(artifacts=artifacts, doc_id="doc"),
        pages=[page],
        diagnostics={
            "effective_config": {"error_policy": {"export_partial_results": True}}
        },
        raw_document={},
        raw_markdown="",
        semantic_groups=[],
        status=status,
        failed_pages=[1] if status == "partial" else [],
        issues=[],
        **empty_fields,
    )


def test_export_writes_hashed_manifest_page_diagnostics_and_status_marker(tmp_path):
    export_pipeline_result(run(tmp_path, "partial"))
    assert (tmp_path / "_PARTIAL").is_file()
    assert not (tmp_path / "_SUCCESS").exists()
    assert not (tmp_path / "_EXPORTING").exists()
    manifest = json.loads((tmp_path / "artifact_manifest.json").read_text())
    assert manifest["run_status"] == "partial"
    assert manifest["status_marker"] == "_PARTIAL"
    assert manifest["package_version"] == "0.1.0"
    assert manifest["attempt_id"]
    first = manifest["files"][0]
    payload = (tmp_path / first["path"]).read_bytes()
    assert first["sha256"] == hashlib.sha256(payload).hexdigest()
    page = json.loads((tmp_path / "page_diagnostics.jsonl").read_text())
    assert page["status"] == "failed"
    assert not list(tmp_path.glob("*.tmp"))


def test_later_success_replaces_stale_partial_marker(tmp_path):
    export_pipeline_result(run(tmp_path, "partial"))
    export_pipeline_result(run(tmp_path, "complete"))
    assert (tmp_path / "_SUCCESS").is_file()
    assert not (tmp_path / "_PARTIAL").exists()


def test_partial_export_can_be_disabled(tmp_path):
    value = run(tmp_path, "partial")
    value.diagnostics["effective_config"]["error_policy"]["export_partial_results"] = (
        False
    )
    with pytest.raises(RuntimeError, match="partial result export"):
        export_pipeline_result(value)
