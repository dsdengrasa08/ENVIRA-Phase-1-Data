import json

from envira_pdf_layout.artifact_validation import (
    validate_exported_artifacts,
    validate_relationship_graph,
)
from envira_pdf_layout.stage_trace import snapshot


def region(region_id):
    return {
        "layout_region_id": region_id,
        "page_number": 1,
        "type": "Text",
        "bbox_px": [0, 0, 10, 10],
    }


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_graph_validator_rejects_missing_endpoints_and_observations():
    result = validate_relationship_graph(
        [region("a")],
        [
            {
                "relationship_id": "r1",
                "kind": "CONTAINMENT_CANDIDATE",
                "left_region_id": "a",
                "right_region_id": "missing",
            }
        ],
    )
    assert not result["valid"]
    assert {error["error"] for error in result["errors"]} == {
        "missing_endpoint",
        "unresolved_containment_candidate",
    }


def test_export_validator_checks_partition_graph_and_trace_schema(tmp_path):
    physical = [region("a")]
    (tmp_path / "effective_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pipeline_diagnostics.json").write_text("{}", encoding="utf-8")
    write_jsonl(tmp_path / "physical_layout_regions.jsonl", physical)
    write_jsonl(tmp_path / "top_level_layout_regions.jsonl", physical)
    write_jsonl(tmp_path / "nested_layout_regions.jsonl", [])
    write_jsonl(tmp_path / "layout_relationships.jsonl", [])
    write_jsonl(tmp_path / "stage_trace.jsonl", [snapshot("final", physical)])
    write_jsonl(
        tmp_path / "page_diagnostics.jsonl", [{"page_number": 1, "status": "completed"}]
    )
    (tmp_path / "artifact_manifest.json").write_text(
        json.dumps({"schema_version": 1, "files": []}), encoding="utf-8"
    )
    assert validate_exported_artifacts(tmp_path)["valid"]


def test_export_validator_reports_missing_and_invalid_artifacts(tmp_path):
    (tmp_path / "effective_config.json").write_text("not-json", encoding="utf-8")
    result = validate_exported_artifacts(tmp_path)
    assert not result["valid"]
    assert any(error["error"] == "invalid_json" for error in result["errors"])
    assert any(error["error"] == "missing" for error in result["errors"])
