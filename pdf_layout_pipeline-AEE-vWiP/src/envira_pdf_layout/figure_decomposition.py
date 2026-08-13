"""Conservative decomposition of under-segmented Figure regions.

Splitting is deliberately semantic-first: independent Figure caption identities are
required, image components must support them, and the joint assignment must be
unambiguous.  Whitespace, size, or page columns can never split a Figure alone.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .caption_association import parse_caption_reference
from .config import FigureFilterConfig
from .schema import initialize_region_schema
from .types import LayoutRegion


@dataclass(frozen=True)
class FigureDecompositionResult:
    regions: list[LayoutRegion]
    proposals: list[dict[str, Any]]
    replaced_regions: list[LayoutRegion]

    @property
    def diagnostics(self) -> dict[str, Any]:
        return {
            "proposal_count": len(self.proposals),
            "accepted_count": sum(p["decision"] == "accepted" for p in self.proposals),
            "ambiguous_count": sum(
                p["decision"] == "preserve_ambiguous" for p in self.proposals
            ),
            "replaced_region_count": len(self.replaced_regions),
            "proposals": self.proposals,
        }


def _page_size(page: dict[str, Any]) -> tuple[float, float]:
    return (
        float(page.get("image_width_px") or page.get("width_px") or 1),
        float(page.get("image_height_px") or page.get("height_px") or 1),
    )


def _caption_identity(region: LayoutRegion) -> tuple[str, str] | None:
    reference = parse_caption_reference(region.get("text") or region.get("orig"))
    return (
        (reference.kind, reference.number.casefold())
        if reference and reference.kind == "figure"
        else None
    )


def _caption_candidates(
    figure: LayoutRegion,
    regions: list[LayoutRegion],
    page_h: float,
    conflicting_parent_ids: dict[str, str] | None = None,
) -> list[LayoutRegion]:
    fb = list(map(float, figure["bbox_px"]))
    candidates: dict[tuple[str, str], LayoutRegion] = {}
    for caption in regions:
        if caption.get("page_number") != figure.get("page_number"):
            continue
        # Provisional association is supporting evidence, not a prerequisite. An
        # oversized Figure can itself cause the existing column matcher to leave a
        # valid caption unattached. Only a confident association to another parent
        # excludes the caption from this Figure's decomposition hypothesis.
        if conflicting_parent_ids is not None and conflicting_parent_ids.get(
            str(caption["layout_region_id"])
        ) not in {None, str(figure["layout_region_id"])}:
            continue
        identity = _caption_identity(caption)
        if identity is None:
            continue
        cb = list(map(float, caption["bbox_px"]))
        overlap = max(0.0, min(fb[2], cb[2]) - max(fb[0], cb[0])) / max(
            1.0, cb[2] - cb[0]
        )
        gap = max(0.0, max(fb[1], cb[1]) - min(fb[3], cb[3])) / page_h
        if overlap < 0.18 or gap > 0.10:
            continue
        # Detector fragments carrying the same Figure identity count once. Prefer
        # the more informative/larger caption rather than manufacturing multiplicity.
        current = candidates.get(identity)
        if current is None or len(str(caption.get("text") or "")) > len(
            str(current.get("text") or "")
        ):
            candidates[identity] = caption
    return sorted(
        candidates.values(),
        key=lambda r: (r["bbox_px"][1], r["bbox_px"][0], r["layout_region_id"]),
    )


def _foreground_components(
    image: Any, bbox: list[float], minimum_area_ratio: float
) -> tuple[Any, list[list[float]]]:
    from collections import deque
    import numpy as np

    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    crop = np.asarray(image)[max(0, y0) : max(0, y1), max(0, x0) : max(0, x1)]
    if crop.size == 0:
        return None, []
    gray = np.mean(crop[..., :3], axis=2) if crop.ndim == 3 else crop
    # Work on a bounded-resolution density mask. Max-pooling retains fine plot
    # strokes while keeping the dependency-free component walk predictable.
    step = max(1, int(max(gray.shape) / 600))
    h = gray.shape[0] // step
    w = gray.shape[1] // step
    reduced = gray[: h * step, : w * step].reshape(h, step, w, step).min(axis=(1, 3))
    mask = reduced < 245
    crop_area = float(crop.shape[0] * crop.shape[1])
    components = []
    # Keep small textual/chart pieces for grouping, while excluding speckle noise.
    noise_floor = max(4.0, crop_area * min(0.0002, minimum_area_ratio / 20))
    visited = np.zeros(mask.shape, dtype=bool)
    for sy, sx in zip(*np.nonzero(mask & ~visited)):
        if visited[sy, sx]:
            continue
        queue = deque([(int(sy), int(sx))])
        visited[sy, sx] = True
        xs, ys = [], []
        while queue:
            cy, cx = queue.popleft()
            xs.append(cx)
            ys.append(cy)
            for ny in range(max(0, cy - 1), min(h, cy + 2)):
                for nx in range(max(0, cx - 1), min(w, cx + 2)):
                    if mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((ny, nx))
        area = len(xs) * step * step
        if float(area) >= noise_floor:
            components.append(
                [
                    float(min(xs) * step + x0),
                    float(min(ys) * step + y0),
                    float((max(xs) + 1) * step + x0),
                    float((max(ys) + 1) * step + y0),
                    float(area),
                ]
            )
    full_mask = np.repeat(np.repeat(mask, step, axis=0), step, axis=1)
    return full_mask[: crop.shape[0], : crop.shape[1]], components


def _assignment_score(
    component: list[float], caption: LayoutRegion, page_h: float
) -> float:
    cb = list(map(float, caption["bbox_px"]))
    overlap = max(0.0, min(component[2], cb[2]) - max(component[0], cb[0])) / max(
        1.0, min(component[2] - component[0], cb[2] - cb[0])
    )
    ccx, ccy = (component[0] + component[2]) / 2, (component[1] + component[3]) / 2
    bx, by = (cb[0] + cb[2]) / 2, (cb[1] + cb[3]) / 2
    distance = (
        ((ccx - bx) / max(1.0, cb[2] - cb[0])) ** 2 + ((ccy - by) / page_h) ** 2
    ) ** 0.5
    # Figure captions are normally below their visual. A caption above a component
    # is still possible, but is weaker evidence than the same caption immediately
    # below a component; this disambiguates vertically stacked Figure/caption pairs.
    direction = (
        0.08 if cb[1] >= component[3] else -0.35 if cb[3] <= component[1] else 0.0
    )
    return overlap + direction - 0.50 * distance


def _groups_for_captions(
    components: list[list[float]],
    captions: list[LayoutRegion],
    page_h: float,
    margin: float,
) -> tuple[list[list[list[float]]], float] | None:
    if len(components) < len(captions):
        return None
    groups: list[list[list[float]]] = [[] for _ in captions]
    weighted_margin = total_weight = 0.0
    # Group every component around the semantic caption anchors. Selecting only
    # the k largest components fails when two large panels belong to one caption:
    # both seeds then represent the same Figure and displace the other Figure.
    for component in components:
        ranked = sorted(
            (
                (_assignment_score(component, caption, page_h), i)
                for i, caption in enumerate(captions)
            ),
            reverse=True,
        )
        if not ranked:
            continue
        groups[ranked[0][1]].append(component)
        weight = float(component[4])
        component_margin = ranked[0][0] - ranked[1][0] if len(ranked) > 1 else 1.0
        weighted_margin += weight * component_margin
        total_weight += weight
    assignment_margin = weighted_margin / max(1.0, total_weight)
    if any(not group for group in groups) or assignment_margin < margin:
        return None
    return groups, assignment_margin


def _group_bbox(group: list[list[float]]) -> list[float]:
    return [
        min(c[0] for c in group),
        min(c[1] for c in group),
        max(c[2] for c in group),
        max(c[3] for c in group),
    ]


def _bridge_ratio(mask: Any, parent: list[float], boxes: list[list[float]]) -> float:
    """Measure foreground in pairwise separating corridors; overlap means no clean cut."""
    import numpy as np

    px0, py0 = int(round(parent[0])), int(round(parent[1]))
    values = []
    for i, left in enumerate(boxes):
        for right in boxes[i + 1 :]:
            if left[2] <= right[0] or right[2] <= left[0]:
                a, b = sorted((left, right), key=lambda box: box[0])
                if any(
                    other is not left
                    and other is not right
                    and a[2] < (other[0] + other[2]) / 2 < b[0]
                    for other in boxes
                ):
                    continue
                x0, x1 = int(a[2] - px0), int(b[0] - px0)
                y0, y1 = int(max(a[1], b[1]) - py0), int(min(a[3], b[3]) - py0)
            elif left[3] <= right[1] or right[3] <= left[1]:
                a, b = sorted((left, right), key=lambda box: box[1])
                if any(
                    other is not left
                    and other is not right
                    and a[3] < (other[1] + other[3]) / 2 < b[1]
                    for other in boxes
                ):
                    continue
                y0, y1 = int(a[3] - py0), int(b[1] - py0)
                x0, x1 = int(max(a[0], b[0]) - px0), int(min(a[2], b[2]) - px0)
            else:
                return 1.0
            corridor = mask[max(0, y0) : max(0, y1), max(0, x0) : max(0, x1)]
            values.append(float(np.count_nonzero(corridor)) / max(1, corridor.size))
    return max(values, default=1.0)


def decompose_oversized_figures(
    regions: list[LayoutRegion],
    pages: list[dict[str, Any]],
    config: FigureFilterConfig,
    provisional_caption_relationships: list[dict[str, Any]] | None = None,
) -> FigureDecompositionResult:
    """Return derived Figures only when semantic, visual, and assignment evidence agree."""
    if not config.decompose_oversized:
        return FigureDecompositionResult(list(regions), [], [])
    from PIL import Image

    working = deepcopy(regions)
    page_map = {int(page["page_number"]): page for page in pages}
    page_images: dict[int, Any] = {}
    proposals: list[dict[str, Any]] = []
    replacements: dict[str, list[LayoutRegion]] = {}
    replaced: list[LayoutRegion] = []
    by_page: dict[int, list[LayoutRegion]] = defaultdict(list)
    for region in working:
        by_page[int(region["page_number"])].append(region)
    provisional_parent_ids = (
        {
            str(relation["child_region_id"]): str(relation["parent_region_id"])
            for relation in provisional_caption_relationships
            if relation.get("status") == "associated"
            and relation.get("parent_region_id") is not None
        }
        if provisional_caption_relationships is not None
        else None
    )
    for figure in (r for r in working if r.get("type") == "Figure"):
        page_number = int(figure["page_number"])
        page = page_map.get(page_number)
        if not page:
            continue
        page_w, page_h = _page_size(page)
        captions = _caption_candidates(
            figure, by_page[page_number], page_h, provisional_parent_ids
        )
        if len(captions) < config.decomposition_min_caption_identities:
            continue
        image = page_images.get(page_number)
        if image is None:
            try:
                image = Image.open(Path(page["page_image_path"])).convert("RGB")
            except (FileNotFoundError, OSError):
                image = None
            page_images[page_number] = image
        base = {
            "page_number": page_number,
            "figure_region_id": str(figure["layout_region_id"]),
            "source_bbox_px": list(figure["bbox_px"]),
            "caption_region_ids": [str(c["layout_region_id"]) for c in captions],
            "caption_identities": [_caption_identity(c) for c in captions],
        }
        if image is None:
            proposals.append(
                {
                    **base,
                    "decision": "preserve_ambiguous",
                    "reason": "page_image_unavailable",
                    "confidence": "low",
                    "proposed_bbox_px": [],
                }
            )
            continue
        mask, components = _foreground_components(
            image,
            list(figure["bbox_px"]),
            config.decomposition_min_component_area_ratio,
        )
        assigned = _groups_for_captions(
            components, captions, page_h, config.decomposition_min_assignment_margin
        )
        if assigned is None:
            proposals.append(
                {
                    **base,
                    "decision": "preserve_ambiguous",
                    "reason": "component_assignment_ambiguous",
                    "confidence": "low",
                    "component_count": len(components),
                    "proposed_bbox_px": [],
                }
            )
            continue
        groups, assignment_margin = assigned
        boxes = [_group_bbox(group) for group in groups]
        parent_area = max(
            1.0,
            (figure["bbox_px"][2] - figure["bbox_px"][0])
            * (figure["bbox_px"][3] - figure["bbox_px"][1]),
        )
        substantial = all(
            (b[2] - b[0]) * (b[3] - b[1]) / parent_area
            >= config.decomposition_min_component_area_ratio
            for b in boxes
        )
        bridge = _bridge_ratio(mask, list(figure["bbox_px"]), boxes)
        if not substantial or bridge > config.decomposition_max_foreground_bridge_ratio:
            proposals.append(
                {
                    **base,
                    "decision": "preserve_ambiguous",
                    "reason": "insufficient_visual_separation",
                    "confidence": "low",
                    "component_count": len(components),
                    "proposed_bbox_px": boxes,
                    "foreground_bridge_ratio": bridge,
                }
            )
            continue
        pad = config.decomposition_padding_page_ratio * max(page_w, page_h)
        children = []
        for index, (box, caption) in enumerate(zip(boxes, captions), 1):
            child = deepcopy(figure)
            child_id = f"{figure['layout_region_id']}__decomposed_{index:02d}"
            padded = [
                max(figure["bbox_px"][0], box[0] - pad),
                max(figure["bbox_px"][1], box[1] - pad),
                min(figure["bbox_px"][2], box[2] + pad),
                min(figure["bbox_px"][3], box[3] + pad),
            ]
            child.update(
                layout_region_id=child_id,
                bbox_px=padded,
                source_region_ids=[str(figure["layout_region_id"])],
                source_bbox_px=list(figure["bbox_px"]),
                resolved_bbox_px=padded,
                physical_bbox_px=padded,
                visual_crop_bbox_px=padded,
                semantic_group_bbox_px=padded,
                synthetic_region=True,
                synthetic_detection_method="caption_visual_figure_decomposition",
                decomposition_parent_region_id=str(figure["layout_region_id"]),
                decomposition_caption_region_id=str(caption["layout_region_id"]),
                geometry_version=int(figure.get("geometry_version") or 1) + 1,
            )
            child["geometry_history"] = list(figure.get("geometry_history") or []) + [
                {
                    "geometry_history_schema_version": 1,
                    "geometry_version": child["geometry_version"],
                    "stage": "figure_decomposition",
                    "reason": "independent_caption_identity_and_visual_component",
                    "source_bbox_px": list(figure["bbox_px"]),
                    "proposed_bbox_px": padded,
                    "resolved_bbox_px": padded,
                    "accepted": True,
                }
            ]
            initialize_region_schema(child, page_record=page)
            children.append(child)
        replacements[str(figure["layout_region_id"])] = children
        replaced.append(deepcopy(figure))
        proposals.append(
            {
                **base,
                "decision": "accepted",
                "reason": "independent_caption_identities_with_separable_components",
                "confidence": "high",
                "derived_region_ids": [c["layout_region_id"] for c in children],
                "proposed_bbox_px": boxes,
                "component_count": len(components),
                "assignment_margin": assignment_margin,
                "foreground_bridge_ratio": bridge,
            }
        )
    output = []
    for region in working:
        output.extend(replacements.get(str(region["layout_region_id"]), [region]))
    return FigureDecompositionResult(output, proposals, replaced)
