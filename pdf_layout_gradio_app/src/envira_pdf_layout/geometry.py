"""Side-effect-free coordinate and bounding-box utilities."""

from __future__ import annotations
from typing import Any
from .types import BBox


def clip_bbox(bbox: BBox, width: float, height: float) -> BBox:
    x0, y0, x1, y1 = bbox
    return (
        max(0.0, min(x0, width)),
        max(0.0, min(y0, height)),
        max(0.0, min(x1, width)),
        max(0.0, min(y1, height)),
    )


def int_bbox(bbox: BBox) -> tuple[int, int, int, int]:
    return tuple(int(round(value)) for value in bbox)  # type: ignore[return-value]


def bbox_area(bbox: BBox) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def intersection_area(a: BBox, b: BBox) -> float:
    return bbox_area(
        (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    )


def coverage(inner: BBox, outer: BBox) -> float:
    area = bbox_area(inner)
    return intersection_area(inner, outer) / area if area else 0.0


def docling_bbox_to_px(
    bbox: Any,
    page_width_pt: float,
    page_height_pt: float,
    width_px: int,
    height_px: int,
) -> BBox:
    left, top, right, bottom = (float(getattr(bbox, k)) for k in ("l", "t", "r", "b"))
    origin = str(
        getattr(
            getattr(bbox, "coord_origin", "TOPLEFT"),
            "value",
            getattr(bbox, "coord_origin", "TOPLEFT"),
        )
    ).upper()
    if "BOTTOMLEFT" in origin:
        top, bottom = page_height_pt - top, page_height_pt - bottom
    y0, y1 = sorted((top, bottom))
    return clip_bbox(
        (
            left * width_px / page_width_pt,
            y0 * height_px / page_height_pt,
            right * width_px / page_width_pt,
            y1 * height_px / page_height_pt,
        ),
        width_px,
        height_px,
    )
