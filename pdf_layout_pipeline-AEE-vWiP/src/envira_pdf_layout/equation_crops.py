"""Context-aware visual crop expansion for displayed Equations.

Physical detector geometry remains unchanged.  Only ``visual_crop_bbox_px`` is
refined, so extra reading whitespace cannot perturb hierarchy or reading order.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import numpy as np

from .config import EquationCropConfig
from .geometry import clip_bbox, intersection_area
from .types import LayoutRegion


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
    if not path or not Path(path).is_file():
        return None
    try:
        from PIL import Image

        return np.asarray(Image.open(path).convert("L"))
    except (OSError, ValueError):
        return None


def _trim_to_empty_margin(
    source: list[float],
    candidate: list[float],
    image: np.ndarray | None,
    config: EquationCropConfig,
) -> list[float]:
    """Keep added bands as whitespace; stop before unrelated visible ink."""
    if image is None:
        return candidate
    height, width = image.shape[:2]
    sx0, sy0, sx1, sy1 = [int(round(v)) for v in source]
    cx0, cy0, cx1, cy1 = [int(round(v)) for v in candidate]
    sx0, cx0 = max(0, sx0), max(0, cx0)
    sy0, cy0 = max(0, sy0), max(0, cy0)
    sx1, cx1 = min(width, sx1), min(width, cx1)
    sy1, cy1 = min(height, sy1), min(height, cy1)
    threshold, minimum = config.ink_threshold, config.minimum_ink_pixels

    # Search from the Equation outward. An occupied scan line is a content wall;
    # the blank lines before it remain useful reading margin.
    left = sx0
    for x in range(sx0 - 1, cx0 - 1, -1):
        if int(np.count_nonzero(image[cy0:cy1, x] < threshold)) >= minimum:
            break
        left = x
    right = sx1
    for x in range(sx1, cx1):
        if int(np.count_nonzero(image[cy0:cy1, x] < threshold)) >= minimum:
            break
        right = x + 1
    top = sy0
    for y in range(sy0 - 1, cy0 - 1, -1):
        if int(np.count_nonzero(image[y, cx0:cx1] < threshold)) >= minimum:
            break
        top = y
    bottom = sy1
    for y in range(sy1, cy1):
        if int(np.count_nonzero(image[y, cx0:cx1] < threshold)) >= minimum:
            break
        bottom = y + 1
    return [float(left), float(top), float(right), float(bottom)]


def _already_has_margin(
    source: list[float],
    image: np.ndarray | None,
    desired_x: float,
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
        float(xs.min()) >= desired_x
        and float(x1 - x0 - 1 - xs.max()) >= desired_x
        and float(ys.min()) >= desired_y
        and float(y1 - y0 - 1 - ys.max()) >= desired_y
    )


def _column_limits(
    target: LayoutRegion, regions: list[LayoutRegion], page_w: float
) -> tuple[float, float]:
    column = target.get("reading_order_column")
    if column in {None, "single"}:
        return 0.0, page_w
    own = [r for r in regions if r.get("reading_order_column") == column]
    other = [
        r
        for r in regions
        if r.get("reading_order_column") not in {None, "single", column}
    ]
    if not own or not other:
        return 0.0, page_w
    tb = list(map(float, target["bbox_px"]))
    left, right = 0.0, page_w
    other_left = [float(r["bbox_px"][2]) for r in other if r["bbox_px"][2] <= tb[0]]
    other_right = [float(r["bbox_px"][0]) for r in other if r["bbox_px"][0] >= tb[2]]
    if other_left:
        own_left = min(float(r["bbox_px"][0]) for r in own)
        left = (max(other_left) + own_left) / 2
    if other_right:
        own_right = max(float(r["bbox_px"][2]) for r in own)
        right = (own_right + min(other_right)) / 2
    return left, right


def _parent_bounds(
    region: LayoutRegion, by_id: dict[str, LayoutRegion]
) -> list[float] | None:
    parent_ids = list(region.get("nested_parent_region_ids") or [])
    boxes = [by_id[str(rid)]["bbox_px"] for rid in parent_ids if str(rid) in by_id]
    if not boxes:
        return None
    # The tightest containing parent is the safest structural crop boundary.
    return list(map(float, min(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))))


def refine_equation_visual_crops(
    regions: list[LayoutRegion],
    pages: list[dict[str, Any]],
    config: EquationCropConfig | None = None,
) -> EquationCropResult:
    """Add a bounded whitespace collar to Formula/Equation visual crops."""
    config = config or EquationCropConfig()
    working = deepcopy(regions)
    if not config.enabled:
        return EquationCropResult(working, [], False)
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
        desired_x = min(equation_h * config.horizontal_margin_height_ratio, cap)
        desired_y = min(
            max(
                equation_h * config.vertical_margin_height_ratio,
                page_h * config.minimum_vertical_margin_page_ratio,
            ),
            cap,
        )
        clearance = equation_h * config.minimum_clearance_height_ratio
        column_left, column_right = _column_limits(target, working, page_w)
        limits = [column_left, 0.0, column_right, page_h]
        blockers: dict[str, str] = {}
        if column_left > 0:
            blockers["left"] = "column"
        if column_right < page_w:
            blockers["right"] = "column"

        image = _load_gray(page)
        if _already_has_margin(source, image, desired_x, desired_y, config):
            target["visual_crop_bbox_px"] = source
            decisions.append(
                {
                    "stage": "equation_visual_crop_refinement",
                    "region_id": str(target["layout_region_id"]),
                    "source_bbox_px": source,
                    "resolved_visual_crop_bbox_px": source,
                    "decision": "preserved",
                    "reason": "sufficient_existing_visual_margin",
                }
            )
            continue

        parent = _parent_bounds(target, by_id)
        if parent:
            limits = [
                max(limits[0], parent[0]),
                max(limits[1], parent[1]),
                min(limits[2], parent[2]),
                min(limits[3], parent[3]),
            ]
            blockers.update(
                left="parent", top="parent", right="parent", bottom="parent"
            )

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

        for neighbor in working:
            if neighbor is target or neighbor.get("type") not in PROTECTED_TYPES:
                continue
            if str(neighbor["layout_region_id"]) in associated_number_ids:
                continue
            nb = list(map(float, neighbor["bbox_px"]))
            same_formula_family = neighbor.get("type") in FORMULA_TYPES
            vertical_corridor = _axis_overlap(source[1], source[3], nb[1], nb[3])
            horizontal_corridor = _axis_overlap(source[0], source[2], nb[0], nb[2])
            nid = str(neighbor["layout_region_id"])
            if vertical_corridor >= config.neighbor_corridor_overlap_ratio:
                if nb[2] <= source[0]:
                    boundary = (nb[2] + source[0]) / 2 if same_formula_family else nb[2]
                    value = boundary + clearance / (2 if same_formula_family else 1)
                    if value > limits[0]:
                        limits[0], blockers["left"] = value, nid
                elif nb[0] >= source[2]:
                    boundary = (source[2] + nb[0]) / 2 if same_formula_family else nb[0]
                    value = boundary - clearance / (2 if same_formula_family else 1)
                    if value < limits[2]:
                        limits[2], blockers["right"] = value, nid
            if horizontal_corridor >= config.neighbor_corridor_overlap_ratio:
                if nb[3] <= source[1]:
                    boundary = (nb[3] + source[1]) / 2 if same_formula_family else nb[3]
                    value = boundary + clearance / (2 if same_formula_family else 1)
                    if value > limits[1]:
                        limits[1], blockers["top"] = value, nid
                elif nb[1] >= source[3]:
                    boundary = (source[3] + nb[1]) / 2 if same_formula_family else nb[1]
                    value = boundary - clearance / (2 if same_formula_family else 1)
                    if value < limits[3]:
                        limits[3], blockers["bottom"] = value, nid

        # A visual crop may expand or remain unchanged, but must never crop away
        # any part of the authoritative Equation when clearance is unavailable.
        limits = [
            min(limits[0], content_source[0]),
            min(limits[1], content_source[1]),
            max(limits[2], content_source[2]),
            max(limits[3], content_source[3]),
        ]
        candidate = [
            max(limits[0], content_source[0] - desired_x),
            max(limits[1], content_source[1] - desired_y),
            min(limits[2], content_source[2] + desired_x),
            min(limits[3], content_source[3] + desired_y),
        ]
        candidate = list(clip_bbox(tuple(candidate), page_w, page_h))
        candidate = _trim_to_empty_margin(content_source, candidate, image, config)

        # Last-resort validation against physical protected regions. Touching is safe;
        # any positive-area intersection introduced by the crop is not.
        invalid = False
        for neighbor in working:
            if neighbor is target or neighbor.get("type") not in PROTECTED_TYPES:
                continue
            if str(neighbor["layout_region_id"]) in associated_number_ids:
                continue
            if intersection_area(tuple(candidate), tuple(neighbor["bbox_px"])) > 0:
                if intersection_area(tuple(source), tuple(neighbor["bbox_px"])) == 0:
                    invalid = True
                    blockers["validation"] = str(neighbor["layout_region_id"])
                    break
        if invalid:
            candidate = source
        target["visual_crop_bbox_px"] = candidate
        did_change = candidate != source
        changed = changed or did_change
        decisions.append(
            {
                "stage": "equation_visual_crop_refinement",
                "region_id": str(target["layout_region_id"]),
                "source_bbox_px": source,
                "desired_margin_px": {"horizontal": desired_x, "vertical": desired_y},
                "safe_limits_px": limits,
                "resolved_visual_crop_bbox_px": candidate,
                "blockers": blockers,
                "associated_equation_number_region_ids": sorted(associated_number_ids),
                "decision": "accepted" if did_change else "preserved",
                "reason": "bounded_whitespace_margin"
                if did_change
                else "no_safe_margin",
            }
        )
    return EquationCropResult(working, decisions, changed)
