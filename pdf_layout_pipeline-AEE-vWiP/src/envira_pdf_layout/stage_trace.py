"""Deterministic stage snapshots for pipeline observability and regression audits."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from typing import Any

from .types import LayoutRegion

TRACE_SCHEMA_VERSION = 1


def snapshot(
    stage: str,
    regions: list[LayoutRegion],
    *,
    previous: dict[str, Any] | None = None,
    relationships: list[dict[str, Any]] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    elapsed_ms: float | None = None,
    status: str = "completed",
) -> dict[str, Any]:
    """Summarize a stage without copying full region payloads into diagnostics."""
    ids = [str(region.get("layout_region_id")) for region in regions]
    missing_id_indices = [
        index
        for index, region in enumerate(regions)
        if not region.get("layout_region_id")
    ]
    invalid_page_ids = []
    pages: Counter[int] = Counter()
    for region in regions:
        try:
            pages[int(region["page_number"])] += 1
        except (KeyError, TypeError, ValueError):
            invalid_page_ids.append(str(region.get("layout_region_id")))
    types = Counter(str(region.get("type") or "Unknown") for region in regions)
    prior_ids = set(previous.get("region_ids", [])) if previous else set()
    current_ids = set(ids)
    invalid_geometry_ids = []
    signatures: dict[str, dict[str, Any]] = {}
    for region in regions:
        region_id = str(region.get("layout_region_id"))
        bbox = region.get("bbox_px") or []
        if (
            len(bbox) != 4
            or not all(isinstance(value, (int, float)) for value in bbox)
            or not all(math.isfinite(float(value)) for value in bbox)
            or float(bbox[2]) <= float(bbox[0])
            or float(bbox[3]) <= float(bbox[1])
        ):
            invalid_geometry_ids.append(region_id)
        signatures[region_id] = {
            "page_number": region.get("page_number"),
            "type": region.get("type"),
            "bbox_px": list(bbox) if isinstance(bbox, (list, tuple)) else bbox,
        }
    previous_signatures = previous.get("region_signatures", {}) if previous else {}
    shared_ids = current_ids & set(previous_signatures)
    geometry_changed_ids = sorted(
        region_id
        for region_id in shared_ids
        if signatures[region_id]["bbox_px"]
        != previous_signatures[region_id].get("bbox_px")
    )
    type_changed_ids = sorted(
        region_id
        for region_id in shared_ids
        if signatures[region_id]["type"] != previous_signatures[region_id].get("type")
    )
    digest = hashlib.sha256(
        json.dumps(signatures, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "stage": stage,
        "status": status,
        "elapsed_ms": round(elapsed_ms, 3) if elapsed_ms is not None else None,
        "region_count": len(regions),
        "region_ids": ids,
        "region_signatures": signatures,
        "region_digest": digest,
        "added_region_ids": sorted(current_ids - prior_ids),
        "removed_region_ids": sorted(prior_ids - current_ids),
        "geometry_changed_region_ids": geometry_changed_ids,
        "type_changed_region_ids": type_changed_ids,
        "counts_by_page": {str(key): pages[key] for key in sorted(pages)},
        "counts_by_type": {key: types[key] for key in sorted(types)},
        "relationship_count": len(relationships or []),
        "decision_count": len(decisions or []),
        "invariants": {
            "unique_region_ids": len(ids) == len(current_ids),
            "all_region_ids_present": not missing_id_indices,
            "valid_page_numbers": not invalid_page_ids,
            "valid_geometry": not invalid_geometry_ids,
            "missing_region_id_indices": missing_id_indices,
            "invalid_page_number_region_ids": invalid_page_ids,
            "invalid_geometry_region_ids": invalid_geometry_ids,
        },
    }


def validate_trace(trace: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [
        {"stage": row["stage"], "invariants": row["invariants"]}
        for row in trace
        if row.get("trace_schema_version") != TRACE_SCHEMA_VERSION
        or row.get("status") != "completed"
        or any(value is False for value in row["invariants"].values())
    ]
    return {
        "valid": not failures,
        "stage_count": len(trace),
        "total_elapsed_ms": round(
            sum(row.get("elapsed_ms") or 0.0 for row in trace), 3
        ),
        "failures": failures,
    }


def compare_stage_traces(
    baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return the first semantic divergence between two exported traces."""
    baseline_by_stage = {row["stage"]: row for row in baseline}
    candidate_by_stage = {row["stage"]: row for row in candidate}
    ordered = [row["stage"] for row in baseline]
    missing = [stage for stage in ordered if stage not in candidate_by_stage]
    unexpected = [
        stage for stage in candidate_by_stage if stage not in baseline_by_stage
    ]
    differences = []
    for stage in ordered:
        if stage not in candidate_by_stage:
            continue
        left, right = baseline_by_stage[stage], candidate_by_stage[stage]
        if left.get("trace_schema_version") != right.get("trace_schema_version"):
            differences.append({"stage": stage, "reason": "schema_version"})
            continue
        if left.get("region_digest") == right.get("region_digest"):
            continue
        left_signatures, right_signatures = (
            left.get("region_signatures", {}),
            right.get("region_signatures", {}),
        )
        shared = set(left_signatures) & set(right_signatures)
        differences.append(
            {
                "stage": stage,
                "reason": "region_digest",
                "baseline_digest": left.get("region_digest"),
                "candidate_digest": right.get("region_digest"),
                "added_region_ids": sorted(
                    set(right_signatures) - set(left_signatures)
                ),
                "removed_region_ids": sorted(
                    set(left_signatures) - set(right_signatures)
                ),
                "geometry_changed_region_ids": sorted(
                    rid
                    for rid in shared
                    if left_signatures[rid].get("bbox_px")
                    != right_signatures[rid].get("bbox_px")
                ),
                "type_changed_region_ids": sorted(
                    rid
                    for rid in shared
                    if left_signatures[rid].get("type")
                    != right_signatures[rid].get("type")
                ),
            }
        )
    compatible = not missing and not unexpected and not differences
    return {
        "compatible": compatible,
        "first_divergent_stage": differences[0]["stage"] if differences else None,
        "missing_stages": missing,
        "unexpected_stages": unexpected,
        "differences": differences,
    }


def tabular_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten invariants and omit signature maps from human-facing tables."""
    return [
        {
            key: value
            for key, value in row.items()
            if key not in {"region_signatures", "invariants"}
        }
        | {
            f"invariant_{key}": value
            for key, value in row.get("invariants", {}).items()
        }
        for row in trace
    ]
