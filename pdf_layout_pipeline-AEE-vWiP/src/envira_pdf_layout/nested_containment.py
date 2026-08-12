"""Non-destructive nested-asset relationship validation and hierarchy ordering."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .config import ContainmentConfig
from .geometry import bbox_area, intersection_area
from .types import LayoutRegion
from .region_index import RegionIndex

CONTAINER_TYPES = {"Figure", "Table", "List", "Form", "Key-value"}
TEXT_TYPES = {"Text", "Title", "Section-header", "Caption", "Footnote", "Reference"}
CONTAINMENT_POLICIES = {
    "Figure": {
        "compatible": {
            "panel_label",
            "figure_internal_text",
            "formula",
            "code",
            "caption_identifier",
        },
        "invalid": {"body_paragraph", "section_heading", "table", "figure"},
    },
    "Table": {
        "compatible": {"table_cell_text", "formula", "code", "table_note"},
        "invalid": {"figure", "table", "section_heading"},
    },
    "List": {
        "compatible": {"list_item", "list_text"},
        "invalid": {"figure", "table", "section_heading"},
    },
    "Form": {
        "compatible": {"form_field", "form_text", "key_value"},
        "invalid": {"figure", "table", "section_heading"},
    },
    "Key-value": {
        "compatible": {"form_field", "form_text", "key_value"},
        "invalid": {"figure", "table", "section_heading"},
    },
}


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
    child_center = (
        (child_bbox[0] + child_bbox[2]) / 2,
        (child_bbox[1] + child_bbox[3]) / 2,
    )
    return {
        "child_coverage": intersection / child_area if child_area else 0.0,
        "parent_coverage": intersection / parent_area if parent_area else 0.0,
        "child_area": child_area,
        "parent_area": parent_area,
        "child_center_inside_parent": (
            parent_bbox[0] <= child_center[0] <= parent_bbox[2]
            and parent_bbox[1] <= child_center[1] <= parent_bbox[3]
        ),
        "child_text_bearing": bool(
            str(child.get("text") or child.get("orig") or "").strip()
        ),
        "parent_figure_completed": bool(
            parent.get("figure_completion_original_bbox_px")
            or parent.get("figure_completion_completed_from_region_ids")
        ),
        "source_bbox": list(child.get("source_bbox_px") or child["bbox_px"]),
        "parent_source_bbox": list(parent.get("source_bbox_px") or parent["bbox_px"]),
        "text_relation": _text_relation(child, parent),
    }


def _normalized_text(region: LayoutRegion) -> str:
    return " ".join(
        str(region.get("text") or region.get("orig") or "").casefold().split()
    )


def _text_relation(child: LayoutRegion, parent: LayoutRegion) -> str:
    child_text, parent_text = _normalized_text(child), _normalized_text(parent)
    if not child_text or not parent_text:
        return "unavailable"
    if child_text == parent_text:
        return "equal"
    if child_text in parent_text:
        return "child_in_parent"
    if parent_text in child_text:
        return "parent_in_child"
    return "different"


def infer_child_role(
    child: LayoutRegion, parent: LayoutRegion, config: ContainmentConfig
) -> tuple[str, list[str]]:
    """Infer an explainable local role before consulting the compatibility matrix."""
    child_type, parent_type = (
        str(child.get("type") or "Unknown"),
        str(parent.get("type") or "Unknown"),
    )
    text = " ".join(str(child.get("text") or child.get("orig") or "").split())
    evidence = [
        f"child_type:{child_type}",
        f"parent_type:{parent_type}",
        f"text_chars:{len(text)}",
    ]
    if child_type in {"Formula", "Equation"}:
        return "formula", evidence
    if child_type == "Code":
        return "code", evidence
    if child_type in {"Title", "Section-header"}:
        return "section_heading", evidence
    if child_type == "Figure":
        return "figure", evidence
    if child_type == "Table":
        return "table", evidence
    if child_type in {
        "Field-region",
        "Field-heading",
        "Field-item",
        "Field-key",
        "Field-value",
    }:
        return "form_field", evidence
    if child_type == "Key-value":
        return "key_value", evidence
    if parent_type == "List" and child_type in {"List", "Text"}:
        return ("list_item" if child_type == "List" else "list_text"), evidence
    if parent_type in {"Form", "Key-value"} and child_type in {"Text", "List"}:
        return "form_text", evidence
    if child_type == "Caption":
        if len(text) <= config.caption_identifier_max_chars:
            return "caption_identifier", evidence
        return "full_caption", evidence
    if parent_type == "Figure" and child_type in {"Text", "Footnote", "Unknown"}:
        if len(text) <= config.panel_label_max_chars:
            return "panel_label", evidence
        if len(text) >= config.body_paragraph_min_chars:
            return "body_paragraph", evidence
        return "figure_internal_text", evidence
    if parent_type == "Table" and child_type == "Footnote":
        return "table_note", evidence
    if parent_type == "Table" and child_type in {"Text", "Unknown"}:
        return "table_cell_text", evidence
    if child_type in TEXT_TYPES:
        return "body_paragraph" if len(
            text
        ) >= config.body_paragraph_min_chars else "text_fragment", evidence
    return "unknown", evidence


def analyze_nested_containment(
    regions: list[LayoutRegion],
    observations: list[dict[str, Any]] | None = None,
    *,
    config: ContainmentConfig | None = None,
    index: RegionIndex | None = None,
    metrics: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Generate page-local proposals without removing or mutating any region."""
    config = config or ContainmentConfig()
    index = index or RegionIndex.build(regions, [])
    by_id = index.by_id
    metrics = metrics if metrics is not None else {}
    metrics.update(observations_examined=0, pairs_scored=0, proposals_emitted=0)
    if observations is not None:
        proposals = []
        for relation in observations:
            metrics["observations_examined"] += 1
            if relation.get("kind") != "CONTAINMENT_CANDIDATE":
                continue
            parent_id = str(relation["candidate_parent_region_id"])
            child_id = str(relation["candidate_child_region_id"])
            if parent_id not in by_id or child_id not in by_id:
                continue
            parent, child = by_id[parent_id], by_id[child_id]
            observed = relation.get("features")
            features = containment_features(child, parent)
            if observed:
                child_is_left = relation.get("left_region_id") == child_id
                features.update(
                    {
                        "child_coverage": observed[
                            "a_containment" if child_is_left else "b_containment"
                        ],
                        "parent_coverage": observed[
                            "b_containment" if child_is_left else "a_containment"
                        ],
                        "child_center_inside_parent": observed[
                            "a_center_inside_b"
                            if child_is_left
                            else "b_center_inside_a"
                        ],
                        "text_relation": observed.get(
                            "text_relation", features["text_relation"]
                        ),
                    }
                )
            else:
                metrics["pairs_scored"] += 1
            proposals.append(_proposal(child, parent, features))
        metrics["proposals_emitted"] = len(proposals)
        return proposals
    proposals = []
    for page_regions in index.by_page.values():
        parents = page_regions
        for child in page_regions:
            child_id = str(child["layout_region_id"])
            for parent in parents:
                metrics["observations_examined"] += 1
                parent_id = str(parent["layout_region_id"])
                if child_id == parent_id:
                    continue
                features = containment_features(child, parent)
                metrics["pairs_scored"] += 1
                if not (
                    features["child_coverage"] >= config.strong_child_coverage
                    or (
                        features["child_center_inside_parent"]
                        and features["child_coverage"] >= config.center_child_coverage
                    )
                ):
                    continue
                if features["parent_area"] <= features["child_area"]:
                    continue
                proposals.append(_proposal(child, parent, features))
    metrics["proposals_emitted"] = len(proposals)
    return proposals


def _proposal(
    child: LayoutRegion, parent: LayoutRegion, features: dict[str, Any]
) -> dict[str, Any]:
    page_number = int(child["page_number"])
    parent_id, child_id = (
        str(parent["layout_region_id"]),
        str(child["layout_region_id"]),
    )
    return {
        "proposal_id": f"p{page_number}:{parent_id}:{child_id}",
        "page_number": page_number,
        "parent_region_id": parent_id,
        "child_region_id": child_id,
        "parent_type": parent.get("type"),
        "child_type": child.get("type"),
        "features": features,
        "previous_behavior": "would_have_been_excluded",
    }


def _classify(
    proposal: dict[str, Any],
    child: LayoutRegion,
    parent: LayoutRegion,
    config: ContainmentConfig,
) -> tuple[str, str, str, list[str]]:
    parent_type, child_type = proposal["parent_type"], proposal["child_type"]
    features = proposal["features"]
    role, role_evidence = infer_child_role(child, parent, config)
    child_parent_ratio = features["child_area"] / max(features["parent_area"], 1.0)
    if child_parent_ratio > config.max_child_parent_area_ratio:
        return (
            "AMBIGUOUS_CONTAINMENT",
            "child_too_large_for_parent",
            role,
            role_evidence,
        )
    if parent_type not in CONTAINER_TYPES:
        relation = proposal["features"].get("text_relation")
        if parent_type in TEXT_TYPES and child_type in TEXT_TYPES:
            if parent_type in {"Title", "Section-header"} and child_type == "Text":
                return (
                    "INVALID_OCCLUSION",
                    "heading_covers_body_text",
                    role,
                    role_evidence,
                )
            if relation == "equal":
                return "DUPLICATE", "equal_text_containment", role, role_evidence
            if parent_type == "Caption" and role in {
                "text_fragment",
                "caption_identifier",
            }:
                return (
                    "IDENTIFIER_FRAGMENT",
                    "caption_contains_identifier_fragment",
                    role,
                    role_evidence,
                )
            return (
                "AMBIGUOUS_TEXT_OCCLUSION",
                "text_container_not_hierarchy_capable",
                role,
                role_evidence,
            )
        if parent_type == "Unknown":
            return (
                "AMBIGUOUS_CONTAINMENT",
                "unknown_parent_capability",
                role,
                role_evidence,
            )
        return "INVALID_OCCLUSION", "parent_not_container_capable", role, role_evidence
    if features["parent_figure_completed"] and child_type in TEXT_TYPES:
        return (
            "AMBIGUOUS_CONTAINMENT",
            "expanded_asset_captures_text",
            role,
            role_evidence,
        )
    policy = CONTAINMENT_POLICIES[parent_type]
    if (
        parent_type == "Table"
        and role == "table_note"
        and features["child_coverage"] < config.strong_child_coverage
    ):
        return (
            "AMBIGUOUS_CONTAINMENT",
            "table_note_not_strongly_contained",
            role,
            role_evidence,
        )
    if role in policy["compatible"]:
        return "NESTED_CHILD", "compatible_container_child_role", role, role_evidence
    if role in policy["invalid"]:
        return (
            "INVALID_OCCLUSION",
            "incompatible_container_child_role",
            role,
            role_evidence,
        )
    return (
        "AMBIGUOUS_CONTAINMENT",
        "unrecognized_container_child_role",
        role,
        role_evidence,
    )


def resolve_nested_hierarchy(
    regions: list[LayoutRegion],
    proposals: list[dict[str, Any]] | None = None,
    config: ContainmentConfig | None = None,
) -> HierarchyResult:
    """Resolve proposals once, retaining ambiguous candidates at top level."""
    working = deepcopy(regions)
    config = config or ContainmentConfig()
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
        kind, reason, role, role_evidence = _classify(
            proposal, by_id[child_id], by_id[parent_id], config
        )
        enriched = {
            **proposal,
            "inferred_child_role": role,
            "role_evidence": role_evidence,
            "policy_rule": f"{proposal['parent_type']}:{role}:{kind}",
            "figure_completion_involved": bool(
                proposal["features"].get("parent_figure_completed")
            ),
        }
        candidates_by_child[child_id].append((enriched, kind, reason))

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
