"""Validate exported pipeline artifacts and relationship graph contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable
from .config import SecurityConfig
from .security import ArtifactSecurityError, resolve_artifact_path, sha256_file
from .schema import (
    COMPLETION_PROPOSAL_SCHEMA_VERSION,
    RELATIONSHIP_SCHEMA_VERSION,
    validate_region_schema,
)


def validate_relationship_graph(
    regions: Iterable[dict[str, Any]], relationships: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    ids = {str(region["layout_region_id"]) for region in regions}
    errors: list[dict[str, Any]] = []
    authoritative_pairs: set[tuple[str, str]] = set()
    for relationship in relationships:
        kind = str(relationship.get("kind") or "")
        relationship_id = relationship.get("relationship_id")
        if (
            relationship.get("relationship_schema_version")
            != RELATIONSHIP_SCHEMA_VERSION
        ):
            errors.append(
                {
                    "relationship_id": relationship_id,
                    "error": "unsupported_relationship_schema",
                }
            )
        endpoints = [
            relationship.get("left_region_id"),
            relationship.get("right_region_id"),
            relationship.get("parent_region_id"),
            relationship.get("child_region_id"),
        ]
        for endpoint in {str(value) for value in endpoints if value is not None}:
            if endpoint not in ids:
                errors.append(
                    {
                        "relationship_id": relationship_id,
                        "error": "missing_endpoint",
                        "region_id": endpoint,
                    }
                )
        if kind == "CONTAINMENT_CANDIDATE":
            errors.append(
                {
                    "relationship_id": relationship_id,
                    "error": "unresolved_containment_candidate",
                }
            )
        if kind in {"NESTED_CHILD", "AMBIGUOUS_CONTAINMENT", "INVALID_OCCLUSION"}:
            pair = (
                str(relationship.get("parent_region_id")),
                str(relationship.get("child_region_id")),
            )
            if pair in authoritative_pairs:
                errors.append(
                    {
                        "relationship_id": relationship_id,
                        "error": "duplicate_authoritative_outcome",
                    }
                )
            authoritative_pairs.add(pair)
    return {"valid": not errors, "errors": errors}


def _read_jsonl(
    path: Path, *, max_line_bytes: int, max_rows: int
) -> list[dict[str, Any]]:
    rows = []
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            if line_number > max_rows:
                raise ValueError("jsonl_row_limit_exceeded")
            if len(line) > max_line_bytes:
                raise ValueError("jsonl_line_limit_exceeded")
            if line.strip():
                rows.append(json.loads(line))
    return rows

def validate_exported_artifacts(
    document_dir: Path, security: SecurityConfig | None = None
) -> dict[str, Any]:
    """Check required JSON/JSONL artifacts and cross-file region references."""
    security = security or SecurityConfig()
    document_dir = Path(document_dir)
    required = {
        "effective_config.json": "json",
        "pipeline_diagnostics.json": "json",
        "page_records.jsonl": "jsonl",
        "physical_layout_regions.jsonl": "jsonl",
        "top_level_layout_regions.jsonl": "jsonl",
        "nested_layout_regions.jsonl": "jsonl",
        "layout_relationships.jsonl": "jsonl",
        "stage_trace.jsonl": "jsonl",
        "page_diagnostics.jsonl": "jsonl",
        "figure_completion_proposals.jsonl": "jsonl",
        "artifact_manifest.json": "json",
    }
    errors = []
    loaded: dict[str, Any] = {}
    total_bytes = 0
    for name, kind in required.items():
        try:
            path = resolve_artifact_path(
                document_dir, name,
                allow_symlinks=security.allow_symlink_artifacts,
            )
        except (ArtifactSecurityError, FileNotFoundError, OSError):
            errors.append({"artifact": name, "error": "missing"})
            continue
        try:
            size = path.stat().st_size
            total_bytes += size
            if size > security.max_artifact_bytes:
                raise ValueError("artifact_size_limit_exceeded")
            if total_bytes > security.max_total_artifact_bytes:
                raise ValueError("total_artifact_size_limit_exceeded")
            loaded[name] = (
                json.loads(path.read_text(encoding="utf-8"))
                if kind == "json"
                else _read_jsonl(
                    path, max_line_bytes=security.max_jsonl_line_bytes,
                    max_rows=security.max_jsonl_rows,
                )
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(
                {"artifact": name, "error": f"invalid_{kind}", "detail": str(exc)}
            )
    physical = loaded.get("physical_layout_regions.jsonl", [])
    top = loaded.get("top_level_layout_regions.jsonl", [])
    nested = loaded.get("nested_layout_regions.jsonl", [])
    if physical and len(physical) != len(top) + len(nested):
        errors.append({"artifact": "hierarchy", "error": "invalid_partition"})
    pages = {
        int(row["page_number"]): row
        for row in loaded.get("page_records.jsonl", [])
        if row.get("page_number") is not None
    }
    for region in physical:
        region_errors = validate_region_schema(
            region, pages.get(int(region.get("page_number", -1)))
        )
        for error in region_errors:
            errors.append(
                {
                    "artifact": "physical_layout_regions.jsonl",
                    "region_id": region.get("layout_region_id"),
                    "error": error,
                }
            )
    graph = validate_relationship_graph(
        physical, loaded.get("layout_relationships.jsonl", [])
    )
    errors.extend(graph["errors"])
    for row in loaded.get("stage_trace.jsonl", []):
        if row.get("trace_schema_version") != 1:
            errors.append(
                {"artifact": "stage_trace.jsonl", "error": "unsupported_schema"}
            )
    for row in loaded.get("figure_completion_proposals.jsonl", []):
        if row.get("proposal_schema_version") != COMPLETION_PROPOSAL_SCHEMA_VERSION:
            errors.append(
                {
                    "artifact": "figure_completion_proposals.jsonl",
                    "error": "unsupported_schema",
                }
            )
    manifest = loaded.get("artifact_manifest.json", {})
    if manifest and manifest.get("schema_version") != 1:
        errors.append(
            {"artifact": "artifact_manifest.json", "error": "unsupported_schema"}
        )
    if manifest:
        seen_paths: set[str] = set()
        for item in manifest.get("files", []):
            if not isinstance(item, dict):
                errors.append({"artifact": "artifact_manifest.json", "error": "invalid_file_entry"})
                continue
            value = item.get("path")
            if not isinstance(value, str) or not value:
                errors.append({"artifact": "artifact_manifest.json", "error": "invalid_manifest_path"})
                continue
            if not isinstance(item.get("bytes"), int) or item.get("bytes", -1) < 0:
                errors.append({"artifact": value, "error": "invalid_declared_size"})
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
                errors.append({"artifact": value, "error": "invalid_sha256"})
                continue
            if value in seen_paths:
                errors.append({"artifact": value, "error": "duplicate_manifest_path"})
                continue
            seen_paths.add(value)
            try:
                path = resolve_artifact_path(
                    document_dir, value,
                    allow_symlinks=security.allow_symlink_artifacts,
                )
                size = path.stat().st_size
                if size != item.get("bytes"):
                    errors.append({"artifact": value, "error": "size_mismatch"})
                    continue
                digest = sha256_file(path, max_bytes=security.max_artifact_bytes)
            except (ArtifactSecurityError, FileNotFoundError, OSError, TypeError) as exc:
                errors.append(
                    {"artifact": value, "error": "unsafe_manifest_path", "detail": str(exc)}
                )
                continue
            if digest != item.get("sha256"):
                errors.append({"artifact": value, "error": "hash_mismatch"})
    truncated = len(errors) > security.max_validation_errors
    errors = errors[: security.max_validation_errors]
    return {"valid": not errors and not truncated, "errors": errors, "errors_truncated": truncated, "artifacts": sorted(loaded)}
