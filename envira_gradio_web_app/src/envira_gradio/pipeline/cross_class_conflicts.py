"""Conservative, provenance-preserving cross-class geometry actions.

Relationship observation remains in :mod:`layout_overlap`.  This module owns the
smaller set of transformations that a class-pair policy can authorize.  Formula /
Text is the first policy; unsupported pairs and ambiguous evidence are retained.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

from .config import OverlapResolutionConfig
from .geometry import bbox_area
from .types import LayoutRegion


FORMULA_TYPES = {"Formula", "Equation"}
GENERIC_TEXT_TYPES = {"Text"}


def _page_size(page: dict[str, Any]) -> tuple[float, float]:
    return (
        float(page.get("image_width_px") or page.get("width_px") or 1),
        float(page.get("image_height_px") or page.get("height_px") or 1),
    )


def _valid_fragment(
    bbox: list[float], page: dict[str, Any], config: OverlapResolutionConfig
) -> bool:
    width, height = _page_size(page)
    fragment_h = max(0.0, bbox[3] - bbox[1])
    return bool(
        fragment_h / height >= config.formula_split_min_fragment_height_page_ratio
        and bbox_area(tuple(bbox)) / (width * height)
        >= config.formula_split_min_fragment_area_page_ratio
    )


def _text_lines(region: LayoutRegion) -> list[str]:
    text = str(region.get("text") or region.get("orig") or "")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _split_payload(
    region: LayoutRegion, upper_height: float, lower_height: float
) -> tuple[str, str] | None:
    """Split only line-addressable payload; never duplicate prose speculatively."""
    lines = _text_lines(region)
    if len(lines) < 2:
        return None
    ratio = upper_height / max(upper_height + lower_height, 1.0)
    cut = min(len(lines) - 1, max(1, round(len(lines) * ratio)))
    return "\n".join(lines[:cut]), "\n".join(lines[cut:])


def _set_geometry(region: LayoutRegion, bbox: list[float], action: str) -> None:
    region.setdefault("source_text", region.get("text"))
    region.setdefault("source_orig", region.get("orig"))
    region["bbox_px"] = list(map(float, bbox))
    region["resolved_bbox_px"] = list(map(float, bbox))
    region["width_px"] = float(bbox[2] - bbox[0])
    region["height_px"] = float(bbox[3] - bbox[1])
    region["area_px"] = float(bbox_area(tuple(bbox)))
    region["geometry_version"] = int(region.get("geometry_version") or 1) + 1
    region["resolution_action"] = action
    region["resolution_status"] = "resolved"


def _clear_resolved_conflict(region: LayoutRegion, relationship_id: str) -> None:
    remaining = [
        item
        for item in region.get("unresolved_conflict_ids", [])
        if item != relationship_id
    ]
    if remaining:
        region["unresolved_conflict_ids"] = remaining
        region["resolution_status"] = "ambiguous"
    else:
        region.pop("unresolved_conflict_ids", None)
        region["resolution_status"] = "resolved"


def _formula_text_sides(
    relation: dict[str, Any], by_id: dict[str, LayoutRegion]
) -> tuple[LayoutRegion, LayoutRegion] | None:
    left = by_id.get(str(relation.get("left_region_id")))
    right = by_id.get(str(relation.get("right_region_id")))
    if not left or not right:
        return None
    if left.get("type") in FORMULA_TYPES and right.get("type") in GENERIC_TEXT_TYPES:
        return left, right
    if right.get("type") in FORMULA_TYPES and left.get("type") in GENERIC_TEXT_TYPES:
        return right, left
    return None


def _block_formula_evidence(
    formula: LayoutRegion,
    text: LayoutRegion,
    relation: dict[str, Any],
    page: dict[str, Any],
    config: OverlapResolutionConfig,
) -> tuple[bool, list[str]]:
    features = relation["features"]
    formula_is_left = relation["left_region_id"] == formula["layout_region_id"]
    formula_coverage = features[
        "a_containment" if formula_is_left else "b_containment"
    ]
    formula_horizontal = features[
        "a_horizontal_coverage" if formula_is_left else "b_horizontal_coverage"
    ]
    width, height = _page_size(page)
    fb = list(map(float, formula["bbox_px"]))
    tb = list(map(float, text["bbox_px"]))
    formula_width_ratio = (fb[2] - fb[0]) / width
    formula_height_ratio = (fb[3] - fb[1]) / height
    same_column = (
        formula.get("reading_order_column") == text.get("reading_order_column")
        or formula.get("reading_order_column") is None
        or text.get("reading_order_column") is None
    )
    horizontally_block_like = bool(
        formula_horizontal >= config.formula_min_horizontal_coverage
        and formula_width_ratio >= config.formula_block_min_width_page_ratio
    )
    not_inline = bool(
        (
            formula_height_ratio > config.formula_inline_max_height_page_ratio
            and (tb[3] - tb[1]) >= 1.5 * max(1.0, fb[3] - fb[1])
        )
        or (
            tb[1] < fb[1]
            and fb[3] < tb[3]
            and (tb[3] - tb[1]) >= 2.5 * max(1.0, fb[3] - fb[1])
        )
    )
    evidence = [
        f"formula_coverage:{formula_coverage:.4f}",
        f"formula_horizontal_coverage:{formula_horizontal:.4f}",
        f"formula_width_page_ratio:{formula_width_ratio:.4f}",
        f"formula_height_page_ratio:{formula_height_ratio:.4f}",
        f"same_column:{same_column}",
        f"not_inline:{not_inline}",
    ]
    return (
        formula_coverage >= config.formula_min_coverage
        and horizontally_block_like
        and same_column
        and not_inline,
        evidence,
    )


def _neighbor_context(
    text: LayoutRegion, formula: LayoutRegion, regions: list[LayoutRegion]
) -> dict[str, Any]:
    page = int(text["page_number"])
    column = text.get("reading_order_column")
    fb = list(map(float, formula["bbox_px"]))
    candidates = [
        region
        for region in regions
        if region is not text
        and region is not formula
        and int(region["page_number"]) == page
        and region.get("type") in GENERIC_TEXT_TYPES
        and (
            column is None
            or region.get("reading_order_column") is None
            or region.get("reading_order_column") == column
        )
    ]
    above = [r for r in candidates if float(r["bbox_px"][3]) <= fb[1]]
    below = [r for r in candidates if float(r["bbox_px"][1]) >= fb[3]]
    return {
        "same_column_text_above": bool(above),
        "same_column_text_below": bool(below),
        "nearest_above_region_id": str(max(above, key=lambda r: r["bbox_px"][3])["layout_region_id"])
        if above
        else None,
        "nearest_below_region_id": str(min(below, key=lambda r: r["bbox_px"][1])["layout_region_id"])
        if below
        else None,
    }


def _resolve_oversized_formula_boundaries(
    working: list[LayoutRegion],
    relationships: list[dict[str, Any]],
    pages: dict[int, dict[str, Any]],
    config: OverlapResolutionConfig,
) -> tuple[set[str], list[dict[str, Any]], set[int]]:
    """Shrink Formula edges that shallowly penetrate correct neighboring Text.

    A Text centroid must remain outside the Formula and the intersection must enter
    through exactly one Formula edge. This distinguishes adjacent prose from inline
    text, contained annotations, and prose envelopes spanning a displayed formula.
    All relations for one Formula are evaluated and applied as one component so the
    result cannot depend on pair iteration order.
    """
    by_id = {str(region["layout_region_id"]): region for region in working}
    by_formula: dict[
        str, list[tuple[dict[str, Any], LayoutRegion, LayoutRegion]]
    ] = defaultdict(list)
    for relation in relationships:
        sides = _formula_text_sides(relation, by_id)
        if sides and relation.get("kind") in {
            "CLASS_CONFLICT",
            "CONTAINMENT_CANDIDATE",
        }:
            formula, text = sides
            by_formula[str(formula["layout_region_id"])].append(
                (relation, formula, text)
            )

    resolved_ids: set[str] = set()
    decisions: list[dict[str, Any]] = []
    affected_pages: set[int] = set()
    for formula_id, conflicts in by_formula.items():
        formula = conflicts[0][1]
        page = pages.get(int(formula["page_number"]), {})
        _, page_h = _page_size(page)
        padding = config.formula_protection_padding_page_ratio * page_h
        original = list(map(float, formula["bbox_px"]))
        formula_h = max(1.0, original[3] - original[1])
        proposed_top, proposed_bottom = original[1], original[3]
        accepted: list[tuple[dict[str, Any], LayoutRegion, str, float]] = []

        for relation, _, text in conflicts:
            tb = list(map(float, text["bbox_px"]))
            overlap_h = max(
                0.0, min(original[3], tb[3]) - max(original[1], tb[1])
            )
            if overlap_h <= 0:
                continue
            text_center = (tb[1] + tb[3]) / 2
            formula_center = (original[1] + original[3]) / 2
            formula_is_left = relation["left_region_id"] == formula_id
            horizontal_coverage = relation["features"][
                "a_horizontal_coverage"
                if formula_is_left
                else "b_horizontal_coverage"
            ]
            shallow = (
                overlap_h / formula_h <= config.formula_boundary_band_ratio
                and horizontal_coverage
                >= config.formula_min_horizontal_coverage
            )
            enters_top = (
                tb[1] < original[1] < tb[3] < formula_center
                and text_center < original[1]
            )
            enters_bottom = (
                formula_center < tb[1] < original[3] < tb[3]
                and text_center > original[3]
            )
            if shallow and enters_top:
                proposed_top = max(proposed_top, tb[3] + padding)
                accepted.append((relation, text, "top", overlap_h / formula_h))
            elif shallow and enters_bottom:
                proposed_bottom = min(proposed_bottom, tb[1] - padding)
                accepted.append((relation, text, "bottom", overlap_h / formula_h))

        if not accepted:
            continue
        resolved_bbox = [original[0], proposed_top, original[2], proposed_bottom]
        retained_ratio = max(0.0, proposed_bottom - proposed_top) / formula_h
        if (
            proposed_top >= proposed_bottom
            or retained_ratio < config.formula_boundary_min_retained_height_ratio
            or not _valid_fragment(resolved_bbox, page, config)
        ):
            decisions.append(
                {
                    "action": "defer_ambiguous",
                    "policy": "formula_text_v2",
                    "formula_region_id": formula_id,
                    "relationship_ids": [item[0]["relationship_id"] for item in accepted],
                    "reason": "formula_boundary_correction_failed_safeguards",
                    "retained_height_ratio": retained_ratio,
                    "confidence": "medium",
                }
            )
            continue

        _set_geometry(formula, resolved_bbox, "trim_oversized_formula_boundary")
        affected_pages.add(int(formula["page_number"]))
        for relation, text, edge, penetration in accepted:
            relation_id = relation["relationship_id"]
            resolved_ids.add(relation_id)
            relation["observed_kind"] = relation["kind"]
            relation.update(
                kind="FORMULA_BOUNDARY_RESOLVED",
                status="resolved_cross_class_conflict",
                proposed_action="trim_formula_boundary",
                resolution_policy="formula_text_v2",
            )
            _clear_resolved_conflict(formula, relation_id)
            _clear_resolved_conflict(text, relation_id)
            decisions.append(
                {
                    "action": "trim_formula_boundary",
                    "policy": "formula_text_v2",
                    "formula_region_id": formula_id,
                    "text_region_id": str(text["layout_region_id"]),
                    "relationship_id": relation_id,
                    "adjusted_edge": edge,
                    "formula_penetration_ratio": penetration,
                    "source_bbox_px": original,
                    "resolved_bbox_px": list(resolved_bbox),
                    "reason": "shallow_formula_edge_penetrates_external_text",
                    "confidence": "high",
                }
            )
    return resolved_ids, decisions, affected_pages


def resolve_cross_class_conflicts(
    regions: list[LayoutRegion],
    relationships: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    config: OverlapResolutionConfig,
) -> tuple[list[LayoutRegion], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply high-confidence pair policies; return regions, decisions, suppressed.

    The Formula/Text policy intentionally handles one protected interval per Text
    source. Multiple Formula conflicts are retained for joint future resolution,
    avoiding order-dependent sequential subtraction.
    """
    if not config.resolve_formula_text_conflicts:
        return regions, [], []
    working = deepcopy(regions)
    page_map = {int(page["page_number"]): page for page in pages}
    resolved_formula_relations, decisions, affected_pages = (
        _resolve_oversized_formula_boundaries(
            working, relationships, page_map, config
        )
    )
    by_id = {str(region["layout_region_id"]): region for region in working}
    candidates: dict[str, list[tuple[dict[str, Any], LayoutRegion, LayoutRegion]]] = defaultdict(list)
    for relation in relationships:
        sides = _formula_text_sides(relation, by_id)
        if (
            sides
            and relation["relationship_id"] not in resolved_formula_relations
            and relation.get("kind") in {"CLASS_CONFLICT", "CONTAINMENT_CANDIDATE"}
        ):
            formula, text = sides
            candidates[str(text["layout_region_id"])].append((relation, formula, text))

    new_regions: list[LayoutRegion] = []
    suppressed: list[LayoutRegion] = []
    suppressed_ids: set[str] = set()
    for text_id, conflicts in candidates.items():
        if len(conflicts) != 1:
            for relation, formula, text in conflicts:
                decisions.append(
                    {
                        "action": "defer_ambiguous",
                        "policy": "formula_text_v1",
                        "text_region_id": text_id,
                        "formula_region_id": str(formula["layout_region_id"]),
                        "relationship_id": relation["relationship_id"],
                        "reason": "multiple_formula_intervals_require_joint_resolution",
                        "confidence": "low",
                    }
                )
            continue
        relation, formula, text = conflicts[0]
        page = page_map.get(int(text["page_number"]), {})
        supported, evidence = _block_formula_evidence(formula, text, relation, page, config)
        context = _neighbor_context(text, formula, working)
        base = {
            "policy": "formula_text_v1",
            "text_region_id": text_id,
            "formula_region_id": str(formula["layout_region_id"]),
            "relationship_id": relation["relationship_id"],
            "evidence": evidence,
            "context": context,
        }
        formula_score, text_score = formula.get("score"), text.get("score")
        if relation["features"]["iou"] >= config.duplicate_iou and (
            formula_score is not None or text_score is not None
        ):
            fs = float(formula_score or 0.0)
            ts = float(text_score or 0.0)
            if max(fs, ts) >= config.cross_class_min_survivor_score and abs(fs - ts) >= config.cross_class_score_margin:
                loser, winner = (text, formula) if fs > ts else (formula, text)
                loser_id = str(loser["layout_region_id"])
                suppressed_ids.add(loser_id)
                suppressed.append(deepcopy(loser))
                winner["resolution_action"] = "cross_class_detector_disagreement_winner"
                _clear_resolved_conflict(winner, relation["relationship_id"])
                relation["observed_kind"] = relation["kind"]
                relation.update(
                    kind="CROSS_CLASS_DETECTION_SUPPRESSED",
                    status="resolved_cross_class_conflict",
                    proposed_action="suppress_lower_confidence_detection",
                    resolution_policy="formula_text_v1",
                )
                decisions.append(
                    {
                        **base,
                        "action": "suppress_lower_confidence_detection",
                        "suppressed_region_id": loser_id,
                        "canonical_region_id": str(winner["layout_region_id"]),
                        "reason": "near_identical_geometry_with_calibrated_score_margin",
                        "confidence": "high",
                    }
                )
                continue
        if not supported:
            decisions.append(
                {**base, "action": "keep_both", "reason": "inline_or_insufficient_block_evidence", "confidence": "low"}
            )
            continue
        _, page_h = _page_size(page)
        padding = config.formula_protection_padding_page_ratio * page_h
        tb = list(map(float, text["bbox_px"]))
        fb = list(map(float, formula["bbox_px"]))
        top_height = max(0.0, fb[1] - padding - tb[1])
        bottom_height = max(0.0, tb[3] - fb[3] - padding)
        top = [tb[0], tb[1], tb[2], min(tb[3], fb[1] - padding)]
        bottom = [tb[0], max(tb[1], fb[3] + padding), tb[2], tb[3]]
        top_valid = _valid_fragment(top, page, config)
        bottom_valid = _valid_fragment(bottom, page, config)
        text_h = max(1.0, tb[3] - tb[1])
        near_top = (fb[1] - tb[1]) / text_h <= config.formula_boundary_band_ratio
        near_bottom = (tb[3] - fb[3]) / text_h <= config.formula_boundary_band_ratio

        if top_valid and not bottom_valid and not near_top:
            _set_geometry(text, top, "trim_text_bottom_around_formula")
            action, reason = "trim_text_bottom", "valid_text_above_formula"
        elif bottom_valid and not top_valid and not near_bottom:
            _set_geometry(text, bottom, "trim_text_top_around_formula")
            action, reason = "trim_text_top", "valid_text_below_formula"
        elif top_valid and bottom_valid:
            payload = _split_payload(text, top_height, bottom_height)
            if payload is None:
                decisions.append(
                    {**base, "action": "defer_ambiguous", "reason": "text_payload_not_line_addressable", "confidence": "medium"}
                )
                continue
            source_id = str(text["layout_region_id"])
            source_bbox = list(text.get("source_bbox_px") or tb)
            upper_text, lower_text = payload
            _set_geometry(text, top, "split_text_above_formula")
            text["text"] = upper_text
            text["orig"] = upper_text
            lower = deepcopy(text)
            lower["layout_region_id"] = f"{source_id}__formula_split_02"
            lower["source_region_ids"] = list(dict.fromkeys(text.get("source_region_ids", [source_id]) + [source_id]))
            lower["source_bbox_px"] = source_bbox
            lower["text"] = lower_text
            lower["orig"] = lower_text
            _set_geometry(lower, bottom, "split_text_below_formula")
            new_regions.append(lower)
            action, reason = "split_text_around_semantic_region", "valid_text_above_and_below_formula"
        else:
            decisions.append(
                {**base, "action": "defer_ambiguous", "reason": "residual_fragments_failed_geometry_safeguards", "confidence": "medium"}
            )
            continue

        affected_pages.add(int(text["page_number"]))
        relation["observed_kind"] = relation["kind"]
        relation.update(
            kind="FORMULA_TEXT_BOUNDARY_RESOLVED",
            status="resolved_cross_class_conflict",
            proposed_action=action,
            resolution_policy="formula_text_v1",
        )
        _clear_resolved_conflict(text, relation["relationship_id"])
        _clear_resolved_conflict(formula, relation["relationship_id"])
        decisions.append({**base, "action": action, "reason": reason, "confidence": "high"})

    working = [
        region
        for region in working
        if str(region["layout_region_id"]) not in suppressed_ids
    ]
    working.extend(new_regions)
    _recompute_affected_reading_order(working, affected_pages)
    return working, decisions, suppressed


def _recompute_affected_reading_order(
    regions: list[LayoutRegion], affected_pages: set[int]
) -> None:
    """Restore deterministic local order after a trim/split geometry action."""
    for page_number in affected_pages:
        page_regions = [r for r in regions if int(r["page_number"]) == page_number]
        page_regions.sort(
            key=lambda r: (
                int(r.get("reading_order_band") or 0),
                10**6 if r.get("reading_order_role") == "spanning" else int(r.get("reading_order_column") or 0)
                if isinstance(r.get("reading_order_column"), int)
                else 0,
                float(r["bbox_px"][1]),
                float(r["bbox_px"][0]),
                str(r["layout_region_id"]),
            )
        )
        for order, region in enumerate(page_regions, 1):
            region["layout_reading_order"] = order
            region["visual_overlay_order"] = order
            region["resolved_reading_order"] = order
