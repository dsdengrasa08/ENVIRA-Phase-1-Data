"""Scientific figure completion and compact edge-figure cleanup."""

from __future__ import annotations
import re
from ..config import FigureFilterConfig
from ..types import FilterStageResult, TransformStageResult

_PANEL = re.compile(r"(?:\([a-z]\).*(?:\([b-z]\))|panels?|multi[- ]panel)", re.I)


def filter_small_edge_figures(regions, page_map, config: FigureFilterConfig):
    if not config.filter_small_edge_figures:
        return FilterStageResult(list(regions))
    excluded = []
    kept = []
    for r in regions:
        p = page_map[r["page_number"]]
        x0, y0, x1, y1 = r["bbox_px"]
        wr = (x1 - x0) / p.width_px
        hr = (y1 - y0) / p.height_px
        edge = (
            y1 / p.height_px <= config.header_y1_max
            or y0 / p.height_px >= config.footer_y0_min
        )
        if (
            r["page_number"] > 1
            and r["type"] == "Figure"
            and edge
            and wr < 0.25
            and hr < 0.12
        ):
            excluded.append({**r, "filter_reason": "small_edge_figure_page2_plus"})
        else:
            kept.append(r)
    return FilterStageResult(kept, excluded, {"drop_count": len(excluded)})


def complete_caption_anchored_figures(
    regions, raw_regions, page_map, config: FigureFilterConfig
):
    # Completion remains conservative: record eligible caption/figure pairs while
    # retaining geometry unless a future image-evidence backend confirms expansion.
    decisions = []
    for caption in (
        r
        for r in regions
        if r["type"] == "Caption"
        and re.match(r"^(fig\.?|figure)\s*\d+", r.get("text", ""), re.I)
    ):
        candidates = [
            r
            for r in regions
            if r["page_number"] == caption["page_number"]
            and r["type"] == "Figure"
            and r["bbox_px"][3] <= caption["bbox_px"][1]
        ]
        if candidates:
            figure = min(
                candidates, key=lambda r: caption["bbox_px"][1] - r["bbox_px"][3]
            )
            hint = bool(_PANEL.search(caption.get("text", "")))
            decisions.append(
                {
                    "caption_id": caption["layout_region_id"],
                    "figure_id": figure["layout_region_id"],
                    "multipanel_hint": hint,
                    "completed": False,
                    "reason": (
                        "geometry_preserved_without_image_evidence"
                        if hint
                        else "insufficient_multipanel_caption_evidence"
                    ),
                }
            )
    return TransformStageResult(
        list(regions), {"decisions": decisions, "completion_count": 0}
    )
