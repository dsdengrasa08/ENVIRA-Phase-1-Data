"""Symmetric narrow side-margin text-furniture removal."""

from ..types import FilterStageResult


def filter_side_margin_text_regions(regions, page_map):
    excluded = []
    kept = []
    for r in regions:
        p = page_map[r["page_number"]]
        x0, y0, x1, y1 = r["bbox_px"]
        w = (x1 - x0) / p.width_px
        h = (y1 - y0) / p.height_px
        cx = (x0 + x1) / (2 * p.width_px)
        side = "left" if cx < 0.06 else "right" if cx > 0.94 else None
        if (
            side
            and r["type"] in {"Text", "Footnote", "Unknown"}
            and w < 0.10
            and (h > 0.12 or h < 0.035)
        ):
            excluded.append(
                {**r, "filter_reason": f"{side}_side_margin_text_furniture"}
            )
        else:
            kept.append(r)
    return FilterStageResult(kept, excluded, {"drop_count": len(excluded)})
