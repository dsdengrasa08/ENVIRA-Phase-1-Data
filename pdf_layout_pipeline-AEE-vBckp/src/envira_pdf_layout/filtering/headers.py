"""Recurring later-page header detection."""

from __future__ import annotations
import re
from collections import defaultdict
from ..config import HeaderFilterConfig
from ..types import FilterStageResult, LayoutRegion, PageRecord


def _signature(text):
    return re.sub(r"\d+", "#", re.sub(r"\W+", " ", text.lower())).strip()


def filter_later_page_headers(
    regions: list[LayoutRegion],
    page_map: dict[int, PageRecord],
    config: HeaderFilterConfig,
) -> FilterStageResult:
    if not config.enabled:
        return FilterStageResult(list(regions))
    candidates = []
    signatures = defaultdict(set)
    for r in regions:
        page = page_map[r["page_number"]]
        if (
            r["page_number"] > 1
            and r["bbox_px"][3] / page.height_px <= config.top_band_ratio
        ):
            sig = _signature(r.get("text", ""))
            candidates.append((r, sig))
            if sig:
                signatures[sig].add(r["page_number"])
    recurring = {s for s, p in signatures.items() if len(p) >= config.min_repeat_pages}
    drop_ids = {
        r["layout_region_id"]
        for r, s in candidates
        if r["type"] == "Page-header" or s in recurring
    }
    excluded = [
        {**r, "filter_reason": "later_page_upper_recurring_header"}
        for r in regions
        if r["layout_region_id"] in drop_ids
    ]
    return FilterStageResult(
        [r for r in regions if r["layout_region_id"] not in drop_ids],
        excluded,
        {
            "candidate_count": len(candidates),
            "repeated_signatures": sorted(recurring),
            "drop_count": len(excluded),
        },
    )
