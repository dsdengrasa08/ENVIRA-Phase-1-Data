"""Repeated compact footer-furniture filtering with caption protection."""

from __future__ import annotations
import re
from collections import defaultdict
from ..config import FooterFilterConfig
from ..types import FilterStageResult


def _sig(text):
    return re.sub(r"\W+", "", text.lower())


def filter_repeated_footer_furniture(regions, page_map, config: FooterFilterConfig):
    if not config.enabled:
        return FilterStageResult(list(regions))
    groups = defaultdict(list)
    for r in regions:
        p = page_map[r["page_number"]]
        x0, y0, x1, y1 = r["bbox_px"]
        if (
            y0 / p.height_px >= config.y0_min
            and (x1 - x0) / p.width_px < 0.25
            and (y1 - y0) / p.height_px < 0.10
        ):
            signature = _sig(r.get("text", ""))
            if signature:
                groups[signature].append(r)
    repeated = {
        s
        for s, items in groups.items()
        if len({r["page_number"] for r in items}) >= config.min_repeat_pages
    }
    drop = {
        r["layout_region_id"]
        for s in repeated
        for r in groups[s]
        if r["type"] not in {"Table", "Formula"}
        and not re.match(r"^(fig|figure|table)\s*\d", r.get("text", ""), re.I)
    }
    excluded = [
        {**r, "filter_reason": "repeated_footer_visual_furniture"}
        for r in regions
        if r["layout_region_id"] in drop
    ]
    return FilterStageResult(
        [r for r in regions if r["layout_region_id"] not in drop],
        excluded,
        {"repeated_signatures": sorted(repeated), "drop_count": len(excluded)},
    )
