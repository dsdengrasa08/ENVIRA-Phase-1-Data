"""Convert serialized Docling items into the stable ENVIRA region schema."""

from __future__ import annotations
from collections.abc import Iterable
from typing import Any
from .geometry import clip_bbox
from .types import LayoutRegion, PageSet

_TYPE_MAP = {
    "text": "Text",
    "paragraph": "Text",
    "title": "Title",
    "section_header": "Section-header",
    "list_item": "List",
    "table": "Table",
    "formula": "Formula",
    "code": "Code",
    "caption": "Caption",
    "footnote": "Footnote",
    "reference": "Reference",
    "page_header": "Page-header",
    "page_footer": "Page-footer",
    "picture": "Figure",
    "chart": "Figure",
    "figure": "Figure",
}


def docling_label_to_region_type(label: str) -> str:
    return _TYPE_MAP.get(str(label).lower().replace("-", "_"), "Unknown")


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if "label" in value and ("prov" in value or "bbox" in value):
            yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _bbox(
    item: dict[str, Any], page, provenance: dict[str, Any]
) -> tuple[float, float, float, float] | None:
    value = provenance.get("bbox") or item.get("bbox")
    if not isinstance(value, dict):
        return None
    keys = (
        {"l", "t", "r", "b"}
        if {"l", "t", "r", "b"} <= value.keys()
        else {"x0", "y0", "x1", "y1"}
    )
    if keys == {"l", "t", "r", "b"}:
        x0, y0, x1, y1 = (float(value[k]) for k in ("l", "t", "r", "b"))
    else:
        x0, y0, x1, y1 = (float(value[k]) for k in ("x0", "y0", "x1", "y1"))
    origin = str(value.get("coord_origin", "TOPLEFT")).upper()
    if "BOTTOMLEFT" in origin:
        y0, y1 = page.height_pt - y0, page.height_pt - y1
    y0, y1 = sorted((y0, y1))
    return clip_bbox(
        (
            x0 * page.width_px / page.width_pt,
            y0 * page.height_px / page.height_pt,
            x1 * page.width_px / page.width_pt,
            y1 * page.height_px / page.height_pt,
        ),
        page.width_px,
        page.height_px,
    )


def convert_docling_items(
    raw_document: dict[str, Any], pages: PageSet
) -> list[LayoutRegion]:
    page_map = pages.by_number
    regions = []
    seen = set()
    for index, item in enumerate(_walk(raw_document), 1):
        prov = item.get("prov") or [{}]
        if isinstance(prov, dict):
            prov = [prov]
        for part_index, provenance in enumerate(prov or [{}], 1):
            page_number = int(
                provenance.get("page_no")
                or provenance.get("page_number")
                or item.get("page_no")
                or 1
            )
            if page_number not in page_map:
                continue
            bbox = _bbox(item, page_map[page_number], provenance)
            if bbox is None:
                continue
            label = str(item.get("label", "unknown"))
            text = str(item.get("text") or item.get("orig") or "")
            key = (page_number, label, text, tuple(round(v, 2) for v in bbox))
            if key in seen:
                continue
            seen.add(key)
            x0, y0, x1, y1 = bbox
            regions.append(
                {
                    "layout_region_id": f"p{page_number:04d}_r{index:05d}_{part_index}",
                    "page_number": page_number,
                    "docling_reading_order": index,
                    "docling_label": label,
                    "type": docling_label_to_region_type(label),
                    "text": text,
                    "orig": item.get("orig"),
                    "bbox_px": list(bbox),
                    "width_px": x1 - x0,
                    "height_px": y1 - y0,
                    "area_px": (x1 - x0) * (y1 - y0),
                    "page_image_path": str(page_map[page_number].page_image_path),
                    **{
                        key: item[key]
                        for key in ("text_lines", "ocr_lines", "lines", "typography")
                        if item.get(key)
                    },
                }
            )
    return regions
