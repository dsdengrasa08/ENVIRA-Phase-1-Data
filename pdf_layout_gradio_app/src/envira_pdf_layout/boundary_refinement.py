"""Conflict-driven, provenance-preserving semantic boundary refinement.

The first policy specializes the reusable edge proposal machinery for Figures.
Whitespace creates candidate cuts, while competing semantic geometry, independent
visual cores, and protected content decide whether an edge may shrink or receive a
bounded, visually supported completion into space released by its neighbor.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import numpy as np

from .geometry import bbox_area, intersection_area
from .schema import apply_geometry_change, initialize_region_schema
from .types import LayoutRegion
from .page_resources import load_page_image


PROTECTED_TYPES = {"Caption", "Table", "Formula", "Section-header", "Title"}


@dataclass
class BoundaryRefinementResult:
    regions: list[LayoutRegion]
    proposals: list[dict[str, Any]]
    diagnostics: dict[str, Any]
    changed: bool = False


def _page_size(page: dict[str, Any]) -> tuple[float, float]:
    return (
        float(page.get("image_width_px") or page.get("width_px") or 1),
        float(page.get("image_height_px") or page.get("height_px") or 1),
    )


def _components(image: np.ndarray, box: list[float], config, page_area: float):
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(image.shape[1], x1), min(image.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        return {"x": [], "y": []}
    ink = (image[y0:y1, x0:x1] < config.refinement_ink_threshold).astype(np.uint8)
    minimum = max(4.0, page_area * config.refinement_min_component_area_ratio)
    output_x = []
    # Projection groups are intentionally used instead of a heavy image-processing
    # import at module load time. They retain detached labels/legends that share an
    # occupied row or column with a principal visual component.
    occupied_x = np.flatnonzero(np.any(ink, axis=0))
    if occupied_x.size:
        splits = np.flatnonzero(np.diff(occupied_x) > 2) + 1
        for group in np.split(occupied_x, splits):
            if not group.size:
                continue
            component = ink[:, group[0] : group[-1] + 1]
            ys = np.flatnonzero(np.any(component, axis=1))
            area = int(np.count_nonzero(component))
            if ys.size and area >= minimum:
                output_x.append(
                    [
                        float(x0 + group[0]),
                        float(y0 + ys[0]),
                        float(x0 + group[-1] + 1),
                        float(y0 + ys[-1] + 1),
                    ]
                )
    output_y = []
    occupied_y = np.flatnonzero(np.any(ink, axis=1))
    if occupied_y.size:
        splits = np.flatnonzero(np.diff(occupied_y) > 2) + 1
        for group in np.split(occupied_y, splits):
            if not group.size:
                continue
            component = ink[group[0] : group[-1] + 1, :]
            xs = np.flatnonzero(np.any(component, axis=0))
            area = int(np.count_nonzero(component))
            box = (
                [
                    float(x0 + xs[0]),
                    float(y0 + group[0]),
                    float(x0 + xs[-1] + 1),
                    float(y0 + group[-1] + 1),
                ]
                if xs.size and area >= minimum
                else None
            )
            if box is not None and box not in output_y:
                output_y.append(box)
    return {"x": output_x, "y": output_y}


def _union(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def _owned_core(components, own_box, competing_box, axis: str, first: bool):
    """Select the dominant component anchored away from the competitor.

    Unioning every component inside an oversized source box is circular: content from
    the neighboring Figure can already lie inside that box and then falsely becomes
    part of its core.  Start from the dominant far-side component instead.  Candidate
    cuts still pass removed-ink and semantic-region safeguards, so a detached genuine
    component prevents an unsafe refinement downstream.
    """
    coordinate = 0 if axis == "x" else 1
    far_edge = 2 if axis == "x" else 3
    if first:
        owned = [
            c
            for c in components
            if (c[coordinate] + c[far_edge]) / 2 < competing_box[coordinate]
        ]
        fallback = min(
            components, key=lambda c: (c[coordinate] + c[far_edge]) / 2, default=None
        )
    else:
        owned = [
            c
            for c in components
            if (c[coordinate] + c[far_edge]) / 2 > competing_box[far_edge]
        ]
        fallback = max(
            components, key=lambda c: (c[coordinate] + c[far_edge]) / 2, default=None
        )
    candidates = owned or ([fallback] if fallback else [])
    return (
        list(max(candidates, key=lambda c: bbox_area(tuple(c)))) if candidates else None
    )


def _independent_caption_parents(
    relationships: list[dict[str, Any]] | None,
) -> set[str]:
    return {
        str(r["parent_region_id"])
        for r in relationships or []
        if r.get("kind") == "CAPTION_OF"
        and r.get("status") == "associated"
        and r.get("parent_region_id")
    }


def _valley(
    image: np.ndarray,
    a_core: list[float],
    b_core: list[float],
    axis: str,
    config,
    page_extent: float,
) -> tuple[float, float, float] | None:
    if axis == "x":
        lo, hi = int(np.ceil(a_core[2])), int(np.floor(b_core[0]))
        cross0, cross1 = int(max(a_core[1], b_core[1])), int(min(a_core[3], b_core[3]))
        if cross1 <= cross0:
            cross0, cross1 = (
                int(min(a_core[1], b_core[1])),
                int(max(a_core[3], b_core[3])),
            )
        strip = image[
            max(0, cross0) : min(image.shape[0], cross1),
            max(0, lo) : min(image.shape[1], hi),
        ]
        density = (
            np.mean(strip < config.refinement_ink_threshold, axis=0)
            if strip.size
            else np.array([])
        )
    else:
        lo, hi = int(np.ceil(a_core[3])), int(np.floor(b_core[1]))
        cross0, cross1 = int(max(a_core[0], b_core[0])), int(min(a_core[2], b_core[2]))
        if cross1 <= cross0:
            cross0, cross1 = (
                int(min(a_core[0], b_core[0])),
                int(max(a_core[2], b_core[2])),
            )
        strip = image[
            max(0, lo) : min(image.shape[0], hi),
            max(0, cross0) : min(image.shape[1], cross1),
        ]
        density = (
            np.mean(strip < config.refinement_ink_threshold, axis=1)
            if strip.size
            else np.array([])
        )
    if hi <= lo or not density.size:
        return None
    active = density <= config.refinement_max_valley_density
    padded = np.pad(active.astype(np.int8), (1, 1))
    starts = np.flatnonzero(np.diff(padded) == 1)
    ends = np.flatnonzero(np.diff(padded) == -1)
    minimum = max(2, int(round(page_extent * config.refinement_min_valley_page_ratio)))
    candidates = [(s, e) for s, e in zip(starts, ends) if e - s >= minimum]
    if not candidates:
        return None
    start, end = max(
        candidates,
        key=lambda item: (
            item[1] - item[0],
            -float(np.mean(density[item[0] : item[1]])),
        ),
    )
    return float(lo + start), float(lo + end), float(np.mean(density[start:end]))


def _ink_ratio(image: np.ndarray, box: list[float], threshold: int) -> float:
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    crop = image[
        max(0, y0) : min(image.shape[0], y1), max(0, x0) : min(image.shape[1], x1)
    ]
    return float(np.mean(crop < threshold)) if crop.size else 0.0


def _axis_relationship(
    a: list[float], b: list[float], axis: str, page_extent: float
) -> tuple[float, float]:
    """Return the separating-axis gap and smaller-span cross-axis overlap.

    A zero gap is important: diagnostic boxes that merely touch have no intersection
    area, but still form one connected semantic region in the final overlay.
    """
    if axis == "x":
        gap = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
        overlap = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        smaller_cross_span = min(a[3] - a[1], b[3] - b[1])
    else:
        gap = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
        overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        smaller_cross_span = min(a[2] - a[0], b[2] - b[0])
    return gap / max(page_extent, 1.0), overlap / max(smaller_cross_span, 1.0)


def _protected_intersections(
    candidate_removed: list[float], regions, own_ids: set[str], padding: float
) -> list[str]:
    hits = []
    for region in regions:
        rid = str(region.get("layout_region_id"))
        typ = str(region.get("type"))
        if rid in own_ids or typ == "Figure":
            continue
        text = " ".join(str(region.get("text") or "").split())
        protected = typ in PROTECTED_TYPES or (typ == "Text" and len(text) >= 80)
        box = list(map(float, region["bbox_px"]))
        protected_box = [
            box[0] - padding,
            box[1] - padding,
            box[2] + padding,
            box[3] + padding,
        ]
        if (
            protected
            and intersection_area(tuple(candidate_removed), tuple(protected_box)) > 0
        ):
            hits.append(rid)
    return hits


def refine_figure_boundaries(
    regions: list[LayoutRegion],
    pages: list[dict[str, Any]],
    config,
    caption_relationships: list[dict[str, Any]] | None = None,
) -> BoundaryRefinementResult:
    """Refine unsupported Figure edges where independent semantic objects compete."""
    if not config.refine_boundaries:
        return BoundaryRefinementResult(list(regions), [], {"enabled": False}, False)
    working = deepcopy(regions)
    page_map = {int(p["page_number"]): p for p in pages}
    by_page: dict[int, list[LayoutRegion]] = defaultdict(list)
    for region in working:
        by_page[int(region["page_number"])].append(region)
    caption_parents = _independent_caption_parents(caption_relationships)
    proposals: list[dict[str, Any]] = []
    changed = False
    for page_number, page_regions in by_page.items():
        page = page_map.get(page_number)
        if not page:
            continue
        image = load_page_image(page["page_image_path"], "L")
        if image is None:
            continue
        page_w, page_h = _page_size(page)
        page_area = page_w * page_h
        figures = [r for r in page_regions if r.get("type") == "Figure"]
        competitors = [
            r
            for r in page_regions
            if r.get("type") == "Table"
            or (
                r.get("type") == "Text"
                and len(" ".join(str(r.get("text") or "").split())) >= 80
            )
        ]
        objects = figures + competitors
        components = {
            str(r["layout_region_id"]): _components(
                image, list(r["bbox_px"]), config, page_area
            )
            for r in objects
        }
        # Joint, deterministic processing prevents input-order-dependent pair ownership.
        objects.sort(
            key=lambda r: (
                float(r["bbox_px"][1]),
                float(r["bbox_px"][0]),
                str(r["layout_region_id"]),
            )
        )
        for i, left in enumerate(objects):
            for right in objects[i + 1 :]:
                if left.get("type") != "Figure" and right.get("type") != "Figure":
                    continue
                ab, bb = (
                    list(map(float, left["bbox_px"])),
                    list(map(float, right["bbox_px"])),
                )
                dx = abs((ab[0] + ab[2]) - (bb[0] + bb[2])) / max(page_w, 1.0)
                dy = abs((ab[1] + ab[3]) - (bb[1] + bb[3])) / max(page_h, 1.0)
                axis = "x" if dx >= dy else "y"
                intersection = intersection_area(tuple(ab), tuple(bb))
                smaller_ratio = intersection / max(
                    1.0, min(bbox_area(tuple(ab)), bbox_area(tuple(bb)))
                )
                penetration = (
                    (min(ab[2], bb[2]) - max(ab[0], bb[0]))
                    if axis == "x"
                    else (min(ab[3], bb[3]) - max(ab[1], bb[1]))
                )
                extent = page_w if axis == "x" else page_h
                gap_ratio, cross_axis_overlap = _axis_relationship(ab, bb, axis, extent)
                connected_neighbor = bool(
                    gap_ratio <= config.refinement_max_neighbor_gap_page_ratio
                    and cross_axis_overlap
                    >= config.refinement_min_cross_axis_overlap_ratio
                )
                if intersection <= 0 and not connected_neighbor:
                    continue
                if (
                    not connected_neighbor
                    and smaller_ratio < config.refinement_min_conflict_smaller_ratio
                    and penetration / max(extent, 1.0)
                    < config.refinement_min_penetration_page_ratio
                ):
                    continue
                first, second = (left, right)
                first_box, second_box = ab, bb
                if (axis == "x" and ab[0] > bb[0]) or (axis == "y" and ab[1] > bb[1]):
                    first, second, first_box, second_box = right, left, bb, ab
                first_core = _owned_core(
                    components.get(str(first["layout_region_id"]), {}).get(axis, []),
                    first_box,
                    second_box,
                    axis,
                    True,
                )
                second_core = _owned_core(
                    components.get(str(second["layout_region_id"]), {}).get(axis, []),
                    second_box,
                    first_box,
                    axis,
                    False,
                )
                base = {
                    "page_number": page_number,
                    "figure_region_ids": [
                        str(first["layout_region_id"]),
                        str(second["layout_region_id"]),
                    ],
                    "axis": axis,
                    "intersection_area": intersection,
                    "intersection_over_smaller": smaller_ratio,
                    "neighbor_gap_page_ratio": gap_ratio,
                    "cross_axis_overlap_ratio": cross_axis_overlap,
                    "connected_neighbor": connected_neighbor,
                    "first_visual_core_bbox_px": first_core,
                    "second_visual_core_bbox_px": second_core,
                }
                if not first_core or not second_core:
                    proposals.append(
                        {
                            **base,
                            "decision": "preserve_ambiguous",
                            "reason": "independent_visual_cores_unavailable",
                        }
                    )
                    continue
                valley = _valley(image, first_core, second_core, axis, config, extent)
                independent_captions = all(
                    str(r["layout_region_id"]) in caption_parents
                    for r in (first, second)
                )
                if valley is None:
                    proposals.append(
                        {
                            **base,
                            "decision": "preserve_ambiguous",
                            "reason": "no_persistent_whitespace_valley",
                            "independent_captions": independent_captions,
                        }
                    )
                    continue
                low, high, density = valley
                pair_changes = []
                edge_evaluations = []
                for region, old, core, edge, cut in (
                    (
                        first,
                        first_box,
                        first_core,
                        "right" if axis == "x" else "bottom",
                        low,
                    ),
                    (
                        second,
                        second_box,
                        second_core,
                        "left" if axis == "x" else "top",
                        high,
                    ),
                ):
                    # Competing semantic objects constrain Figure ownership but keep
                    # their own geometry; their class-specific refiners may reuse the
                    # same proposal architecture later.
                    if region.get("type") != "Figure":
                        continue
                    new = list(old)
                    index = {"left": 0, "top": 1, "right": 2, "bottom": 3}[edge]
                    if edge in {"right", "bottom"}:
                        new[index] = cut
                        moving_outward = new[index] > old[index]
                        changed_strip = (
                            [old[2], old[1], new[2], old[3]]
                            if edge == "right" and moving_outward
                            else [new[2], old[1], old[2], old[3]]
                            if edge == "right"
                            else [old[0], old[3], old[2], new[3]]
                            if moving_outward
                            else [old[0], new[3], old[2], old[3]]
                        )
                        unsupported = (
                            [new[2], old[1], high, old[3]]
                            if edge == "right"
                            else [old[0], new[3], old[2], high]
                        )
                    else:
                        new[index] = cut
                        moving_outward = new[index] < old[index]
                        changed_strip = (
                            [new[0], old[1], old[0], old[3]]
                            if edge == "left" and moving_outward
                            else [old[0], old[1], new[0], old[3]]
                            if edge == "left"
                            else [old[0], new[1], old[2], old[1]]
                            if moving_outward
                            else [old[0], old[1], old[2], new[1]]
                        )
                        unsupported = (
                            [low, old[1], new[0], old[3]]
                            if edge == "left"
                            else [old[0], low, old[2], new[1]]
                        )
                    meaningful = new != old
                    preserves_core = (
                        new[0] <= core[0]
                        and new[1] <= core[1]
                        and new[2] >= core[2]
                        and new[3] >= core[3]
                    )
                    # Ink already owned by the competing core is expected in the full
                    # removed strip.  Only the fringe between this core and the valley
                    # measures whether the moving edge itself has visual support.
                    removed_ink = (
                        _ink_ratio(image, unsupported, config.refinement_ink_threshold)
                        if meaningful and not moving_outward
                        else 0.0
                    )
                    added_ink = (
                        _ink_ratio(
                            image, changed_strip, config.refinement_ink_threshold
                        )
                        if meaningful and moving_outward
                        else 0.0
                    )
                    protected = (
                        _protected_intersections(
                            changed_strip,
                            page_regions,
                            {
                                str(first["layout_region_id"]),
                                str(second["layout_region_id"]),
                            },
                            max(page_w, page_h)
                            * config.refinement_protection_padding_page_ratio,
                        )
                        if meaningful
                        else []
                    )
                    expansion_ratio = abs(new[index] - old[index]) / max(extent, 1.0)
                    accepted_edge = bool(
                        meaningful
                        and preserves_core
                        and (
                            moving_outward
                            and added_ink >= config.refinement_min_added_ink_ratio
                            and expansion_ratio
                            <= config.refinement_max_edge_expansion_page_ratio
                            or not moving_outward
                            and removed_ink <= config.refinement_max_removed_ink_ratio
                        )
                        and not protected
                    )
                    edge_evaluations.append(
                        {
                            "figure_region_id": str(region["layout_region_id"]),
                            "edge": edge,
                            "source_bbox_px": list(old),
                            "candidate_bbox_px": list(new),
                            "meaningful": meaningful,
                            "preserves_visual_core": preserves_core,
                            "operation": "expand" if moving_outward else "shrink",
                            "removed_ink_ratio": removed_ink,
                            "added_ink_ratio": added_ink,
                            "edge_change_page_ratio": expansion_ratio,
                            "protected_region_ids": protected,
                            "accepted": accepted_edge,
                        }
                    )
                    if accepted_edge:
                        source = list(region["bbox_px"])
                        apply_geometry_change(
                            region,
                            new,
                            stage="figure_boundary_refinement",
                            reason=(
                                "supported_neighbor_side_boundary_completion"
                                if moving_outward
                                else "unsupported_edge_between_independent_visual_cores"
                            ),
                            accepted=True,
                            page_record=page,
                        )
                        region["physical_bbox_px"] = list(new)
                        region["visual_crop_bbox_px"] = list(new)
                        pair_changes.append(
                            {
                                "figure_region_id": str(region["layout_region_id"]),
                                "edge": edge,
                                "source_bbox_px": source,
                                "resolved_bbox_px": new,
                                "operation": "expand" if moving_outward else "shrink",
                                "removed_ink_ratio": removed_ink,
                                "added_ink_ratio": added_ink,
                            }
                        )
                        changed = True
                proposals.append(
                    {
                        **base,
                        "decision": "accepted"
                        if pair_changes
                        else "preserve_ambiguous",
                        "reason": "evidence_supported_edge_refinement"
                        if pair_changes
                        else "candidate_cut_did_not_pass_safeguards",
                        "independent_captions": independent_captions,
                        "valley": [low, high],
                        "valley_density": density,
                        "changes": pair_changes,
                        "edge_evaluations": edge_evaluations,
                    }
                )
    for region in working:
        initialize_region_schema(
            region, page_record=page_map.get(int(region["page_number"]))
        )
    diagnostics = {
        "enabled": True,
        "proposal_count": len(proposals),
        "accepted_count": sum(p["decision"] == "accepted" for p in proposals),
        "proposals": proposals,
    }
    return BoundaryRefinementResult(working, proposals, diagnostics, changed)
