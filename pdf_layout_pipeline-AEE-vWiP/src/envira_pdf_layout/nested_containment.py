"""Non-destructive nested-asset relationship validation and hierarchy ordering."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .geometry import bbox_area, intersection_area
from .types import LayoutRegion

CONTAINER_TYPES = {"Figure", "Table", "List", "Form", "Key-value"}
TEXT_TYPES = {"Text", "Title", "Section-header", "Caption", "Footnote", "Reference"}


@dataclass(frozen=True)
class HierarchyResult:
    regions: list[LayoutRegion]
    relationships: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    top_level_regions: list[LayoutRegion]
    nested_regions: list[LayoutRegion]
    diagnostics: dict[str, Any]


def containment_features(child: LayoutRegion, parent: LayoutRegion) -> dict[str, Any]:
    child_bbox = tuple(map(float, child["bbox_px"]))
    parent_bbox = tuple(map(float, parent["bbox_px"]))
    child_area, parent_area = bbox_area(child_bbox), bbox_area(parent_bbox)
    intersection = intersection_area(child_bbox, parent_bbox)
    return {
        "child_coverage": intersection / child_area if child_area else 0.0,
        "parent_coverage": intersection / parent_area if parent_area else 0.0,
        "child_area": child_area,
        "parent_area": parent_area,
        "child_text_bearing": bool(
            str(child.get("text") or child.get("orig") or "").strip()
        ),
        "parent_figure_completed": bool(
            parent.get("figure_completion_original_bbox_px")
            or parent.get("figure_completion_completed_from_region_ids")
        ),
        "source_bbox": list(child.get("source_bbox_px") or child["bbox_px"]),
        "parent_source_bbox": list(parent.get("source_bbox_px") or parent["bbox_px"]),
    }


def analyze_nested_containment(
    regions: list[LayoutRegion], *, threshold: float = 0.92
) -> list[dict[str, Any]]:
    """Generate page-local proposals without removing or mutating any region."""
    by_page: dict[int, list[LayoutRegion]] = defaultdict(list)
    for region in regions:
        by_page[int(region["page_number"])].append(region)
    proposals = []
    for page_number, page_regions in by_page.items():
        parents = [r for r in page_regions if r.get("type") in CONTAINER_TYPES]
        for child in page_regions:
            child_id = str(child["layout_region_id"])
            for parent in parents:
                parent_id = str(parent["layout_region_id"])
                if child_id == parent_id:
                    continue
                features = containment_features(child, parent)
                if features["child_coverage"] < threshold:
                    continue
                proposals.append(
                    {
                        "proposal_id": f"p{page_number}:{parent_id}:{child_id}",
                        "page_number": page_number,
                        "parent_region_id": parent_id,
                        "child_region_id": child_id,
                        "parent_type": parent.get("type"),
                        "child_type": child.get("type"),
                        "features": features,
                        "previous_behavior": "would_have_been_excluded",
                    }
                )
    return proposals


def _classify(proposal: dict[str, Any]) -> tuple[str, str]:
    parent_type, child_type = proposal["parent_type"], proposal["child_type"]
    features = proposal["features"]
    if parent_type not in CONTAINER_TYPES:
        return "INVALID_OCCLUSION", "parent_not_container_capable"
    if child_type in CONTAINER_TYPES:
        return "AMBIGUOUS_CONTAINMENT", "nested_container_requires_review"
    if features["parent_figure_completed"] and child_type in TEXT_TYPES:
        return "AMBIGUOUS_CONTAINMENT", "expanded_asset_captures_text"
    if parent_type == "List" and child_type != "List":
        return "AMBIGUOUS_CONTAINMENT", "list_child_role_incompatible"
    return "NESTED_CHILD", "compatible_container_containment"


def resolve_nested_hierarchy(
    regions: list[LayoutRegion],
    proposals: list[dict[str, Any]] | None = None,
) -> HierarchyResult:
    """Resolve proposals once, retaining ambiguous candidates at top level."""
    working = deepcopy(regions)
    for region in working:
        for key in (
            "nested_parent_region_ids",
            "nested_child_region_ids",
            "parent_local_reading_order",
        ):
            region.pop(key, None)
        region["emission_policy"] = "emit_canonical"
    by_id = {str(region["layout_region_id"]): region for region in working}
    proposals = (
        proposals if proposals is not None else analyze_nested_containment(working)
    )
    candidates_by_child: dict[str, list[tuple[dict[str, Any], str, str]]] = defaultdict(
        list
    )
    decisions, relationships = [], []
    for proposal in proposals:
        parent_id, child_id = (
            str(proposal["parent_region_id"]),
            str(proposal["child_region_id"]),
        )
        if parent_id not in by_id or child_id not in by_id:
            decisions.append(
                {**proposal, "action": "reject", "reason": "missing_region_reference"}
            )
            continue
        if by_id[parent_id]["page_number"] != by_id[child_id]["page_number"]:
            decisions.append(
                {**proposal, "action": "reject", "reason": "cross_page_hierarchy"}
            )
            continue
        kind, reason = _classify(proposal)
        candidates_by_child[child_id].append((proposal, kind, reason))

    accepted_parent: dict[str, str] = {}
    for child_id, alternatives in candidates_by_child.items():
        acceptable = [item for item in alternatives if item[1] == "NESTED_CHILD"]
        if len(acceptable) == 1:
            proposal, kind, reason = acceptable[0]
            accepted_parent[child_id] = str(proposal["parent_region_id"])
        elif len(acceptable) > 1:
            proposal, kind, reason = (
                alternatives[0][0],
                "AMBIGUOUS_CONTAINMENT",
                "multiple_plausible_parents",
            )
        else:
            proposal, kind, reason = alternatives[0]
        action = (
            "accept_hierarchy" if child_id in accepted_parent else "retain_top_level"
        )
        decision = {**proposal, "kind": kind, "action": action, "reason": reason}
        decisions.append(decision)
        relationships.append(
            {
                "relationship_id": proposal["proposal_id"],
                "page_number": proposal["page_number"],
                "left_region_id": proposal["parent_region_id"],
                "right_region_id": proposal["child_region_id"],
                "parent_region_id": proposal["parent_region_id"]
                if action == "accept_hierarchy"
                else None,
                "child_region_id": proposal["child_region_id"]
                if action == "accept_hierarchy"
                else None,
                "kind": kind,
                "reason": reason,
                "status": "preserved_as_parent_child"
                if action == "accept_hierarchy"
                else "unresolved_conflict",
                "proposed_action": "associate"
                if action == "accept_hierarchy"
                else "flag",
                "features": proposal["features"],
            }
        )

    children_by_parent: dict[str, list[LayoutRegion]] = defaultdict(list)
    for child_id, parent_id in accepted_parent.items():
        child = by_id[child_id]
        child["nested_parent_region_ids"] = [parent_id]
        child["emission_policy"] = "emit_as_nested_child"
        child["resolved_reading_order"] = None
        children_by_parent[parent_id].append(child)
    for parent_id, children in children_by_parent.items():
        children.sort(
            key=lambda r: (
                float(r["bbox_px"][1]),
                float(r["bbox_px"][0]),
                int(r.get("docling_doc_order", 10**9)),
                str(r["layout_region_id"]),
            )
        )
        by_id[parent_id]["nested_child_region_ids"] = [
            str(child["layout_region_id"]) for child in children
        ]
        for order, child in enumerate(children, 1):
            child["parent_local_reading_order"] = order

    pages: dict[int, list[LayoutRegion]] = defaultdict(list)
    for region in working:
        pages[int(region["page_number"])].append(region)
    top_level = []
    for page_regions in pages.values():
        tops = [
            r for r in page_regions if str(r["layout_region_id"]) not in accepted_parent
        ]
        tops.sort(
            key=lambda r: (
                (
                    r.get("layout_reading_order")
                    if r.get("layout_reading_order") is not None
                    else 10**9
                ),
                float(r["bbox_px"][1]),
                float(r["bbox_px"][0]),
                str(r["layout_region_id"]),
            )
        )
        for order, region in enumerate(tops, 1):
            region["resolved_reading_order"] = order
        top_level.extend(tops)
    nested = [by_id[child_id] for child_id in accepted_parent]
    diagnostics = validate_hierarchy(working, relationships)
    diagnostics.update(
        {
            "proposal_count": len(proposals),
            "accepted_count": len(nested),
            "ambiguous_count": sum(
                d["action"] == "retain_top_level" for d in decisions
            ),
        }
    )
    return HierarchyResult(
        working, relationships, decisions, top_level, nested, diagnostics
    )


def validate_hierarchy(
    regions: list[LayoutRegion], relationships: list[dict[str, Any]]
) -> dict[str, Any]:
    ids = [str(region["layout_region_id"]) for region in regions]
    errors = []
    if len(ids) != len(set(ids)):
        errors.append("duplicate_region_ids")
    by_id = {str(region["layout_region_id"]): region for region in regions}
    parents: dict[str, list[str]] = defaultdict(list)
    for relation in relationships:
        parent, child = (
            relation.get("parent_region_id"),
            relation.get("child_region_id"),
        )
        if not parent or not child:
            continue
        if parent not in ids or child not in ids:
            errors.append("missing_relationship_reference")
            continue
        if parent == child:
            errors.append("self_cycle")
        if by_id[parent]["page_number"] != by_id[child]["page_number"]:
            errors.append("cross_page_hierarchy")
        if by_id[parent].get("type") not in CONTAINER_TYPES:
            errors.append("non_container_parent")
        parents[str(child)].append(str(parent))
    if any(len(value) > 1 for value in parents.values()):
        errors.append("multiple_accepted_parents")
    for start in parents:
        seen, node = set(), start
        while node in parents and parents[node]:
            if node in seen:
                errors.append("hierarchy_cycle")
                break
            seen.add(node)
            node = parents[node][0]
    top_orders: dict[int, list[int]] = defaultdict(list)
    child_orders: dict[str, list[int]] = defaultdict(list)
    for region in regions:
        if region.get("nested_parent_region_ids"):
            child_orders[region["nested_parent_region_ids"][0]].append(
                int(region.get("parent_local_reading_order", 0))
            )
        elif region.get("resolved_reading_order") is not None:
            top_orders[int(region["page_number"])].append(
                int(region["resolved_reading_order"])
            )
    if any(
        sorted(values) != list(range(1, len(values) + 1))
        for values in top_orders.values()
    ):
        errors.append("non_contiguous_top_level_order")
    if any(
        sorted(values) != list(range(1, len(values) + 1))
        for values in child_orders.values()
    ):
        errors.append("non_contiguous_child_order")
    return {
        "valid": not errors,
        "errors": sorted(set(errors)),
        "region_count": len(regions),
    }
