"""Serialization of pipeline results without detection side effects."""

from __future__ import annotations
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from uuid import uuid4
from . import __version__
from .stage_trace import tabular_trace
from .results import summary_dataframe
from .types import ExportManifest
from .security import redact_secrets, sanitize_payload, secure_file, sha256_file


def _write_jsonl(path, rows, mode=0o600):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    secure_file(path, mode)


def _write_text(path, value, mode=0o600):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    secure_file(path, mode)


def export_pipeline_result(run):
    paths = run.document.artifacts
    export_started = datetime.now(timezone.utc)
    for marker_name in ("_SUCCESS", "_PARTIAL", "_FAILED"):
        (paths.document_dir / marker_name).unlink(missing_ok=True)
    publishing_marker = paths.document_dir / "_EXPORTING"
    _write_text(publishing_marker, export_started.isoformat() + "\n")
    effective_config = run.diagnostics.get("effective_config", {})
    privacy = effective_config.get("privacy", {})
    security = effective_config.get("security", {})
    file_mode = int(security.get("secure_file_mode", 0o600))
    include_text = bool(privacy.get("export_region_text", True))
    include_paths = bool(privacy.get("export_source_paths", False))
    exported_config = (
        redact_secrets(effective_config)
        if privacy.get("redact_effective_config", True)
        else effective_config
    )
    if run.status == "partial" and not effective_config.get("error_policy", {}).get(
        "export_partial_results", True
    ):
        raise RuntimeError("partial result export is disabled by error policy")
    _write_text(
        paths.raw_json,
        json.dumps(
            run.raw_document if privacy.get("export_raw_document", False) else {},
            ensure_ascii=False, indent=2, default=str,
        ), file_mode,
    )
    _write_text(
        paths.raw_markdown,
        run.raw_markdown if privacy.get("export_raw_markdown", False) else "",
        file_mode,
    )
    _write_text(
        paths.effective_config_json,
        json.dumps(exported_config, ensure_ascii=False, indent=2),
        file_mode,
    )
    diagnostics = sanitize_payload(
        redact_secrets(dict(run.diagnostics)),
        include_text=privacy.get("diagnostics_detail", "standard") in {"debug", "full"},
        include_paths=include_paths,
    )
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
    def rows(value):
        return sanitize_payload(value, include_text=include_text, include_paths=include_paths)

    _write_jsonl(paths.page_records_jsonl, rows(run.pages), file_mode)
    _write_jsonl(paths.regions_jsonl, rows(run.final_regions), file_mode)
    _write_jsonl(paths.raw_regions_jsonl, rows(run.raw_regions), file_mode)
    _write_jsonl(paths.resolved_regions_jsonl, rows(run.resolved_regions), file_mode)
    _write_jsonl(paths.physical_regions_jsonl, rows(run.physical_regions), file_mode)
    _write_jsonl(paths.top_level_regions_jsonl, rows(run.top_level_regions), file_mode)
    _write_jsonl(paths.nested_regions_jsonl, rows(run.nested_regions), file_mode)
    _write_jsonl(
        paths.figure_completion_proposals_jsonl,
        run.diagnostics.get("figure_completion", {})
        .get("validation", {})
        .get("proposals", []),
    )
    _write_jsonl(paths.caption_relationships_jsonl, rows(run.caption_overlap_relationships), file_mode)
    _write_jsonl(paths.caption_groups_jsonl, rows(run.caption_groups), file_mode)
    _write_jsonl(paths.layout_relationships_jsonl, rows(run.layout_relationships), file_mode)
    _write_jsonl(paths.resolution_decisions_jsonl, rows(run.resolution_decisions), file_mode)
    _write_jsonl(paths.suppressed_regions_jsonl, rows(run.suppressed_regions), file_mode)
    _write_jsonl(paths.post_body_assets_jsonl, rows(run.post_body_assets), file_mode)
    _write_jsonl(paths.post_body_asset_regions_jsonl, rows(run.post_body_asset_regions), file_mode)
    _write_jsonl(paths.logical_tables_jsonl, rows(run.logical_tables), file_mode)
    _write_jsonl(paths.stage_trace_jsonl, run.stage_trace)
    _write_jsonl(
        paths.page_diagnostics_jsonl,
        _page_diagnostics(run),
    )
    summary_dataframe(run).to_csv(paths.summary_csv, index=False)
    secure_file(paths.summary_csv, file_mode)
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
        "run_id": effective_config.get("document", {}).get("run_id") or run.document.doc_id,
        "attempt_id": str(uuid4()),
        "run_status": run.status,
        "artifacts_complete": run.status in {"complete", "complete_with_warnings"},
        "artifact_validation_passed": False,
        "source_pdf_sha256_short": getattr(run.document, "pdf_hash", None),
        "source_pdf_sha256": getattr(run.document, "pdf_sha256", None),
        "source_pdf_bytes": (
            run.document.source_pdf.stat().st_size
            if getattr(run.document, "source_pdf", None) else None
        ),
        "effective_config_sha256": run.diagnostics.get("application", {}).get("effective_config_sha256"),
        "package_version": __version__,
        "git_revision": _git_revision(getattr(paths, "project_dir", paths.document_dir)),
        "python_version": platform.python_version(),
        "remote_services_allowed": run.diagnostics.get("application", {}).get("remote_services_allowed"),
        "environment_sha256": run.diagnostics.get("environment_fingerprint", {}).get("environment_sha256"),
        "dependency_inventory_sha256": run.diagnostics.get("environment_fingerprint", {}).get("dependency_inventory_sha256"),
        "model_manifest_sha256": run.diagnostics.get("environment_fingerprint", {}).get("model_manifest_sha256"),
        "model_file_set_sha256": run.diagnostics.get("environment_fingerprint", {}).get("model_file_set_sha256"),
        "started_at": run.diagnostics.get("started_at"),
        "exported_at": export_started.isoformat(),
        "page_range": [getattr(run.document, "page_start", None), getattr(run.document, "page_end", None)],
        "completed_stages": list(getattr(run, "completed_stages", [])),
        "failed_stages": list(getattr(run, "failed_stages", [])),
        "counts": {
            "pages": len(run.pages),
            "physical_regions": len(run.physical_regions),
            "relationships": len(run.layout_relationships),
        },
        "status_marker": (
            "_SUCCESS" if run.status in {"complete", "complete_with_warnings"}
            else "_PARTIAL" if run.status == "partial" else "_FAILED"
        ),
        "files": [
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "sensitivity": _artifact_sensitivity(path),
            }
            for path in files
        ],
    }
    _write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
    marker = (
        "_SUCCESS"
        if run.status in {"complete", "complete_with_warnings"}
        else "_PARTIAL"
        if run.status == "partial"
        else "_FAILED"
    )
    _write_text(paths.document_dir / marker, run.status + "\n")
    publishing_marker.unlink(missing_ok=True)
    return ExportManifest(files + (manifest_path, paths.document_dir / marker))


def _artifact_sensitivity(path):
    if path.name in {"docling_raw.json", "docling_raw.md"}:
        return "raw_sensitive"
    if path.name in {"artifact_manifest.json", "stage_trace.jsonl"}:
        return "operational_metadata"
    if path.name == "effective_config.json":
        return "secret_redacted"
    return "derived_sensitive"


def mark_manifest_validated(path):
    """Mark post-export validation without changing any hashed payload artifact."""
    value = json.loads(path.read_text(encoding="utf-8"))
    value["artifact_validation_passed"] = True
    value["validated_at"] = datetime.now(timezone.utc).isoformat()
    _write_text(path, json.dumps(value, indent=2) + "\n")


def _git_revision(project_dir):
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project_dir, capture_output=True,
            text=True, timeout=2, check=False,
        )
        return completed.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


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
