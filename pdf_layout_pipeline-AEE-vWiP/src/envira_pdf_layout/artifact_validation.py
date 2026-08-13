"""Validate exported pipeline artifacts and relationship graph contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def validate_relationship_graph(
    regions: Iterable[dict[str, Any]], relationships: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    ids = {str(region["layout_region_id"]) for region in regions}
    errors: list[dict[str, Any]] = []
    authoritative_pairs: set[tuple[str, str]] = set()
    for relationship in relationships:
        kind = str(relationship.get("kind") or "")
        relationship_id = relationship.get("relationship_id")
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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_exported_artifacts(document_dir: Path) -> dict[str, Any]:
    """Check required JSON/JSONL artifacts and cross-file region references."""
    required = {
        "effective_config.json": "json",
        "pipeline_diagnostics.json": "json",
        "physical_layout_regions.jsonl": "jsonl",
        "top_level_layout_regions.jsonl": "jsonl",
        "nested_layout_regions.jsonl": "jsonl",
        "layout_relationships.jsonl": "jsonl",
        "stage_trace.jsonl": "jsonl",
        "page_diagnostics.jsonl": "jsonl",
        "artifact_manifest.json": "json",
    }
    errors = []
    loaded: dict[str, Any] = {}
    for name, kind in required.items():
        path = document_dir / name
        if not path.is_file():
            errors.append({"artifact": name, "error": "missing"})
            continue
        try:
            loaded[name] = (
                json.loads(path.read_text(encoding="utf-8"))
                if kind == "json"
                else _read_jsonl(path)
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(
                {"artifact": name, "error": f"invalid_{kind}", "detail": str(exc)}
            )
    physical = loaded.get("physical_layout_regions.jsonl", [])
    top = loaded.get("top_level_layout_regions.jsonl", [])
    nested = loaded.get("nested_layout_regions.jsonl", [])
    if physical and len(physical) != len(top) + len(nested):
        errors.append({"artifact": "hierarchy", "error": "invalid_partition"})
    graph = validate_relationship_graph(
        physical, loaded.get("layout_relationships.jsonl", [])
    )
    errors.extend(graph["errors"])
    for row in loaded.get("stage_trace.jsonl", []):
        if row.get("trace_schema_version") != 1:
            errors.append(
                {"artifact": "stage_trace.jsonl", "error": "unsupported_schema"}
            )
    manifest = loaded.get("artifact_manifest.json", {})
    if manifest and manifest.get("schema_version") != 1:
        errors.append(
            {"artifact": "artifact_manifest.json", "error": "unsupported_schema"}
        )
    if manifest:
        for item in manifest.get("files", []):
            path = document_dir / item["path"]
            if not path.is_file():
                errors.append(
                    {"artifact": item["path"], "error": "manifest_file_missing"}
                )
                continue
            import hashlib

            if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
                errors.append({"artifact": item["path"], "error": "hash_mismatch"})
    return {"valid": not errors, "errors": errors, "artifacts": sorted(loaded)}
