"""Context-aware visual crop expansion for displayed Equations.

Physical detector geometry remains unchanged.  Only ``visual_crop_bbox_px`` is
refined, so extra reading whitespace cannot perturb hierarchy or reading order.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any

import numpy as np

from .config import EquationCropConfig
from .geometry import clip_bbox, intersection_area
from .types import LayoutRegion
from .page_resources import load_page_image


FORMULA_TYPES = {"Formula", "Equation"}
PROTECTED_TYPES = {
    "Text",
    "List",
    "Caption",
    "Section-header",
    "Title",
    "Table",
    "Figure",
    "Formula",
    "Equation",
    "Footnote",
    "Reference",
    "Code",
    "Page-header",
    "Page-footer",
    "Page-number",
    "Unknown",
}
EQUATION_NUMBER_RE = re.compile(r"^\s*[\(\[]\s*\d+[A-Za-z]?\s*[\)\]]\s*$")


@dataclass
class EquationCropResult:
    regions: list[LayoutRegion]
    decisions: list[dict[str, Any]]
    changed: bool


def equation_crop_bbox(region: LayoutRegion) -> list[float]:
    """Return the downstream crop extent with backward-compatible fallback."""
    return list(map(float, region.get("visual_crop_bbox_px") or region["bbox_px"]))


def _page_size(page: dict[str, Any]) -> tuple[float, float]:
    return (
        float(page.get("image_width_px") or page.get("width_px") or 1),
        float(page.get("image_height_px") or page.get("height_px") or 1),
    )


def _axis_overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    overlap = max(0.0, min(a1, b1) - max(a0, b0))
    return overlap / max(1.0, min(a1 - a0, b1 - b0))


def _load_gray(page: dict[str, Any]) -> np.ndarray | None:
    path = page.get("page_image_path")
    return load_page_image(path, "L") if path else None


def _already_has_margin(
    source: list[float],
    image: np.ndarray | None,
    desired_y: float,
    config: EquationCropConfig,
) -> bool:
    if image is None:
        return False
    height, width = image.shape[:2]
    x0, y0, x1, y1 = [int(round(v)) for v in source]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(width, x1), min(height, y1)
    if x1 <= x0 or y1 <= y0:
        return False
    ys, xs = np.where(image[y0:y1, x0:x1] < config.ink_threshold)
    if len(xs) < config.minimum_ink_pixels:
        return False
    return (
        float(ys.min()) >= desired_y
        and float(y1 - y0 - 1 - ys.max()) >= desired_y
    )


def _parent_bounds(
    region: LayoutRegion, by_id: dict[str, LayoutRegion]
) -> list[float] | None:
    parent_ids = list(region.get("nested_parent_region_ids") or [])
    boxes = [by_id[str(rid)]["bbox_px"] for rid in parent_ids if str(rid) in by_id]
    if not boxes:
        return None
    # The tightest containing parent is the safest structural crop boundary.
    return list(map(float, min(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))))


def _introduces_overlap(
    candidate: list[float],
    baseline: list[float],
    target: LayoutRegion,
    regions: list[LayoutRegion],
    associated_number_ids: set[str],
) -> str | None:
    """Return the first protected neighbor newly intersected by one edge."""
    for neighbor in regions:
        if neighbor is target or neighbor.get("type") not in PROTECTED_TYPES:
            continue
        neighbor_id = str(neighbor["layout_region_id"])
        if neighbor_id in associated_number_ids:
            continue
        neighbor_bbox = tuple(map(float, neighbor["bbox_px"]))
        if (
            intersection_area(tuple(candidate), neighbor_bbox) > 0
            and intersection_area(tuple(baseline), neighbor_bbox) == 0
        ):
            return neighbor_id
    return None


def refine_equation_visual_crops(
    regions: list[LayoutRegion],
    pages: list[dict[str, Any]],
    config: EquationCropConfig | None = None,
) -> EquationCropResult:
    """Add a bounded whitespace collar to Formula/Equation visual crops."""
    config = config or EquationCropConfig()
    if not config.enabled:
        return EquationCropResult(list(regions), [], False)
    if not any(region.get("type") in FORMULA_TYPES for region in regions):
        return EquationCropResult(list(regions), [], False)
    working = deepcopy(regions)
    page_map = {int(page["page_number"]): page for page in pages}
    by_id = {str(region["layout_region_id"]): region for region in working}
    decisions: list[dict[str, Any]] = []
    changed = False

    for target in working:
        if target.get("type") not in FORMULA_TYPES:
            continue
        page = page_map.get(int(target["page_number"]), {})
        page_w, page_h = _page_size(page)
        source = list(map(float, target.get("resolved_bbox_px") or target["bbox_px"]))
        equation_h = max(1.0, source[3] - source[1])
        cap = config.maximum_margin_page_ratio * min(page_w, page_h)
        desired_y = min(
            max(
                equation_h * config.vertical_margin_height_ratio,
                page_h * config.minimum_vertical_margin_page_ratio,
            ),
            cap,
        )
        clearance = equation_h * config.minimum_clearance_height_ratio
        associated_number_ids: set[str] = set()
        content_source = list(source)
        for neighbor in working:
            if neighbor is target or neighbor.get("type") not in {
                "Text",
                "Equation",
                "Formula",
            }:
                continue
            text = str(neighbor.get("text") or neighbor.get("orig") or "")
            nb = list(map(float, neighbor["bbox_px"]))
            vertical_affinity = _axis_overlap(source[1], source[3], nb[1], nb[3])
            horizontal_gap = max(0.0, max(source[0], nb[0]) - min(source[2], nb[2]))
            same_column = neighbor.get("reading_order_column") in {
                None,
                target.get("reading_order_column"),
            }
            if (
                neighbor.get("type") == "Text"
                and EQUATION_NUMBER_RE.match(text)
                and vertical_affinity >= config.neighbor_corridor_overlap_ratio
                and horizontal_gap / max(page_w, 1.0)
                <= config.equation_number_max_gap_page_ratio
                and same_column
            ):
                associated_number_ids.add(str(neighbor["layout_region_id"]))
                content_source = [
                    min(content_source[0], nb[0]),
                    min(content_source[1], nb[1]),
                    max(content_source[2], nb[2]),
                    max(content_source[3], nb[3]),
                ]

        # Expansion is deliberately vertical-only. Horizontal changes represent
        # logical content completion (for example an associated Equation number),
        # never decorative left/right padding.
        content_source = list(clip_bbox(tuple(content_source), page_w, page_h))
        image = _load_gray(page)
        if _already_has_margin(content_source, image, desired_y, config):
            target["visual_crop_bbox_px"] = content_source
            decisions.append(
                {
                    "stage": "equation_visual_crop_refinement",
                    "region_id": str(target["layout_region_id"]),
                    "source_bbox_px": source,
                    "logical_content_bbox_px": content_source,
                    "resolved_visual_crop_bbox_px": content_source,
                    "top_decision": "preserved",
                    "bottom_decision": "preserved",
                    "decision": "preserved",
                    "reason": "sufficient_existing_vertical_margin",
                }
            )
            continue

        top_limit, bottom_limit = 0.0, page_h
        blockers: dict[str, str] = {}
        parent = _parent_bounds(target, by_id)
        if parent:
            top_limit = max(top_limit, parent[1])
            bottom_limit = min(bottom_limit, parent[3])
            blockers.update(top="parent", bottom="parent")

        for neighbor in working:
            if neighbor is target or neighbor.get("type") not in PROTECTED_TYPES:
                continue
            if str(neighbor["layout_region_id"]) in associated_number_ids:
                continue
            nb = list(map(float, neighbor["bbox_px"]))
            same_formula_family = neighbor.get("type") in FORMULA_TYPES
            horizontal_corridor = _axis_overlap(
                content_source[0], content_source[2], nb[0], nb[2]
            )
            nid = str(neighbor["layout_region_id"])
            if horizontal_corridor >= config.neighbor_corridor_overlap_ratio:
                if nb[3] <= content_source[1]:
                    boundary = (
                        (nb[3] + content_source[1]) / 2
                        if same_formula_family
                        else nb[3]
                    )
                    value = boundary + clearance / (2 if same_formula_family else 1)
                    if value > top_limit:
                        top_limit, blockers["top"] = value, nid
                elif nb[1] >= content_source[3]:
                    boundary = (
                        (content_source[3] + nb[1]) / 2
                        if same_formula_family
                        else nb[1]
                    )
                    value = boundary - clearance / (2 if same_formula_family else 1)
                    if value < bottom_limit:
                        bottom_limit, blockers["bottom"] = value, nid

        proposed_top = max(
            min(top_limit, content_source[1]), content_source[1] - desired_y
        )
        proposed_bottom = min(
            max(bottom_limit, content_source[3]), content_source[3] + desired_y
        )

        top_candidate = [
            content_source[0],
            proposed_top,
            content_source[2],
            content_source[3],
        ]
        top_conflict = _introduces_overlap(
            top_candidate,
            content_source,
            target,
            working,
            associated_number_ids,
        )
        resolved_top = content_source[1] if top_conflict else proposed_top
        if top_conflict:
            blockers["top_validation"] = top_conflict

        bottom_candidate = [
            content_source[0],
            content_source[1],
            content_source[2],
            proposed_bottom,
        ]
        bottom_conflict = _introduces_overlap(
            bottom_candidate,
            content_source,
            target,
            working,
            associated_number_ids,
        )
        resolved_bottom = content_source[3] if bottom_conflict else proposed_bottom
        if bottom_conflict:
            blockers["bottom_validation"] = bottom_conflict

        candidate = [
            content_source[0],
            resolved_top,
            content_source[2],
            resolved_bottom,
        ]
        target["visual_crop_bbox_px"] = candidate
        did_change = candidate != content_source or content_source != source
        changed = changed or did_change
        decisions.append(
            {
                "stage": "equation_visual_crop_refinement",
                "region_id": str(target["layout_region_id"]),
                "source_bbox_px": source,
                "logical_content_bbox_px": content_source,
                "desired_margin_px": {"top": desired_y, "bottom": desired_y},
                "safe_limits_px": {"top": top_limit, "bottom": bottom_limit},
                "resolved_visual_crop_bbox_px": candidate,
                "blockers": blockers,
                "associated_equation_number_region_ids": sorted(associated_number_ids),
                "top_decision": "reverted_conflict"
                if top_conflict
                else "expanded"
                if resolved_top < content_source[1]
                else "preserved",
                "bottom_decision": "reverted_conflict"
                if bottom_conflict
                else "expanded"
                if resolved_bottom > content_source[3]
                else "preserved",
                "decision": "accepted" if did_change else "preserved",
                "reason": "bounded_vertical_margin"
                if did_change
                else "no_safe_margin",
            }
        )
    return EquationCropResult(working, decisions, changed)
