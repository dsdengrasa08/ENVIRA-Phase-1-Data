"""Serialization of pipeline results without detection side effects."""

from __future__ import annotations
import json
import hashlib
import os
from .stage_trace import tabular_trace
from .results import summary_dataframe
from .types import ExportManifest


def _write_jsonl(path, rows):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _write_text(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def export_pipeline_result(run):
    paths = run.document.artifacts
    effective_config = run.diagnostics.get("effective_config", {})
    if run.status == "partial" and not effective_config.get("error_policy", {}).get(
        "export_partial_results", True
    ):
        raise RuntimeError("partial result export is disabled by error policy")
    _write_text(
        paths.raw_json,
        json.dumps(run.raw_document, ensure_ascii=False, indent=2, default=str),
    )
    _write_text(paths.raw_markdown, run.raw_markdown)
    _write_text(
        paths.effective_config_json,
        json.dumps(effective_config, ensure_ascii=False, indent=2),
    )
    diagnostics = dict(run.diagnostics)
    if "stage_trace" in diagnostics:
        diagnostics["stage_trace"] = {
            **diagnostics["stage_trace"],
            "stages": tabular_trace(run.stage_trace),
            "signature_storage": "stage_trace.jsonl",
        }
    _write_text(
        paths.diagnostics_json,
        json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str),
    )
    _write_jsonl(paths.page_records_jsonl, run.pages)
    _write_jsonl(paths.regions_jsonl, run.final_regions)
    _write_jsonl(paths.raw_regions_jsonl, run.raw_regions)
    _write_jsonl(paths.resolved_regions_jsonl, run.resolved_regions)
    _write_jsonl(paths.physical_regions_jsonl, run.physical_regions)
    _write_jsonl(paths.top_level_regions_jsonl, run.top_level_regions)
    _write_jsonl(paths.nested_regions_jsonl, run.nested_regions)
    _write_jsonl(
        paths.figure_completion_proposals_jsonl,
        run.diagnostics.get("figure_completion", {})
        .get("validation", {})
        .get("proposals", []),
    )
    _write_jsonl(paths.caption_relationships_jsonl, run.caption_overlap_relationships)
    _write_jsonl(paths.caption_groups_jsonl, run.caption_groups)
    _write_jsonl(paths.layout_relationships_jsonl, run.layout_relationships)
    _write_jsonl(paths.resolution_decisions_jsonl, run.resolution_decisions)
    _write_jsonl(paths.suppressed_regions_jsonl, run.suppressed_regions)
    _write_jsonl(paths.post_body_assets_jsonl, run.post_body_assets)
    _write_jsonl(paths.post_body_asset_regions_jsonl, run.post_body_asset_regions)
    _write_jsonl(paths.logical_tables_jsonl, run.logical_tables)
    _write_jsonl(paths.stage_trace_jsonl, run.stage_trace)
    _write_jsonl(
        paths.page_diagnostics_jsonl,
        _page_diagnostics(run),
    )
    summary_dataframe(run).to_csv(paths.summary_csv, index=False)
    files = (
        paths.raw_json,
        paths.raw_markdown,
        paths.effective_config_json,
        paths.diagnostics_json,
        paths.page_records_jsonl,
        paths.regions_jsonl,
        paths.post_body_assets_jsonl,
        paths.post_body_asset_regions_jsonl,
        paths.logical_tables_jsonl,
        paths.raw_regions_jsonl,
        paths.resolved_regions_jsonl,
        paths.physical_regions_jsonl,
        paths.top_level_regions_jsonl,
        paths.nested_regions_jsonl,
        paths.figure_completion_proposals_jsonl,
        paths.caption_relationships_jsonl,
        paths.caption_groups_jsonl,
        paths.layout_relationships_jsonl,
        paths.resolution_decisions_jsonl,
        paths.suppressed_regions_jsonl,
        paths.summary_csv,
        paths.stage_trace_jsonl,
        paths.page_diagnostics_jsonl,
    )
    manifest_path = paths.artifact_manifest_json
    manifest = {
        "schema_version": 1,
        "run_status": run.status,
        "artifacts_complete": run.status in {"complete", "complete_with_warnings"},
        "files": [
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in files
        ],
    }
    _write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
    for marker in ("_SUCCESS", "_PARTIAL", "_FAILED"):
        (paths.document_dir / marker).unlink(missing_ok=True)
    marker = (
        "_SUCCESS"
        if run.status in {"complete", "complete_with_warnings"}
        else "_PARTIAL"
        if run.status == "partial"
        else "_FAILED"
    )
    _write_text(paths.document_dir / marker, run.status + "\n")
    return ExportManifest(files + (manifest_path, paths.document_dir / marker))


def _page_diagnostics(run):
    issues_by_page = {}
    for issue in run.issues:
        if issue.get("page_number") is not None:
            issues_by_page.setdefault(int(issue["page_number"]), []).append(issue)
    return [
        {
            "schema_version": 1,
            "page_number": int(page["page_number"]),
            "status": "failed"
            if int(page["page_number"]) in run.failed_pages
            else "completed",
            "issues": issues_by_page.get(int(page["page_number"]), []),
            "counts": page.get("counts", {}),
        }
        for page in run.pages
    ]
