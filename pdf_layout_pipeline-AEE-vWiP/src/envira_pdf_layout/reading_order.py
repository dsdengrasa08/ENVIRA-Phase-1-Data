"""Dynamic page-column reading-order assignment."""

from __future__ import annotations
from .config import ReadingOrderConfig


def assign_document_reading_order(regions, page_map, config: ReadingOrderConfig):
    output = []
    metadata = {}
    for page_number, page in page_map.items():
        page_width = float(
            page.get("image_width_px") or page.get("width_px") or 1
        ) if isinstance(page, dict) else float(page.width_px)
        items = [dict(r) for r in regions if r["page_number"] == page_number]
        centers = sorted(
            (r["bbox_px"][0] + r["bbox_px"][2]) / (2 * page_width)
            for r in items
            if r["width_px"] / page_width < 0.75
        )
        gap = max(
            ((b - a, a, b) for a, b in zip(centers, centers[1:])), default=(0, 0, 1)
        )
        split = (gap[1] + gap[2]) / 2 if gap[0] >= config.column_gap_ratio else None

        def key(r):
            center = (r["bbox_px"][0] + r["bbox_px"][2]) / (2 * page_width)
            column = 0 if split is None else (0 if center < split else 1)
            return column, r["bbox_px"][1], r["bbox_px"][0]

        for order, r in enumerate(sorted(items, key=key), 1):
            center = (r["bbox_px"][0] + r["bbox_px"][2]) / (2 * page_width)
            column = (
                "single" if split is None else ("left" if center < split else "right")
            )
            r.update(
                {
                    "layout_reading_order": order,
                    "visual_overlay_order": order,
                    "included_in_layout_reading_order": True,
                    "reading_order_column": column,
                    "reading_order_band": "body",
                    "reading_order_role": "article",
                    "reading_order_excluded_reason": None,
                }
            )
            output.append(r)
        metadata[str(page_number)] = {
            "columns": [] if split is None else [0, split, 1],
            "numbered_region_count": len(items),
            "unnumbered_region_count": 0,
        }
    return output, metadata
