"""Production Docling-item conversion into the stable ENVIRA region schema.

This module owns the backend boundary.  It deliberately preserves the identifiers,
field values, ordering, and skip policy of the formerly embedded core conversion.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .geometry import bbox_area, clip_bbox
from .types import LayoutRegion, PageSet
from .schema import initialize_region_schema


_TYPE_MAP = {
    "title": "Title",
    "section_header": "Section-header",
    "text": "Text",
    "paragraph": "Text",
    "reference": "Reference",
    "list_item": "List",
    "table": "Table",
    "document_index": "Table",
    "picture": "Figure",
    "chart": "Figure",
    "figure": "Figure",
    "caption": "Caption",
    "footnote": "Footnote",
    "formula": "Formula",
    "code": "Code",
    "page_header": "Page-header",
    "page_footer": "Page-footer",
    "form": "Form",
    "key_value_region": "Key-value",
    "field_region": "Field-region",
    "field_heading": "Field-heading",
    "field_item": "Field-item",
    "field_key": "Field-key",
    "field_value": "Field-value",
    "handwritten_text": "Handwritten-text",
}


@dataclass(frozen=True)
class RegionConversionResult:
    """Converted regions and explicit accounting for ignored provenance."""

    regions: list[LayoutRegion]
    item_count: int
    provenance_count: int
    skipped_page_count: int
    skipped_geometry_count: int


def _value(obj: Any, name: str, default: Any = None) -> Any:
    return (
        obj.get(name, default)
        if isinstance(obj, Mapping)
        else getattr(obj, name, default)
    )


def _enum_text(value: Any) -> str:
    if value is None:
        return "unknown"
    return str(value.value) if hasattr(value, "value") else str(value)


def _bbox_dict(bbox: Any) -> dict[str, Any]:
    if bbox is None:
        return {}
    if isinstance(bbox, Mapping):
        return dict(bbox)
    if hasattr(bbox, "model_dump"):
        return bbox.model_dump(mode="json")
    return {
        "l": getattr(bbox, "l", None),
        "t": getattr(bbox, "t", None),
        "r": getattr(bbox, "r", None),
        "b": getattr(bbox, "b", None),
        "coord_origin": _enum_text(getattr(bbox, "coord_origin", "TOPLEFT")),
    }


def docling_label_to_region_type(label: str) -> str:
    """Normalize known Docling labels while retaining readable future labels."""
    normalized = str(label or "unknown").lower().replace("-", "_")
    return _TYPE_MAP.get(normalized, normalized.replace("_", "-").title())


def docling_bbox_to_px(
    bbox: Any, page_record: Mapping[str, Any]
) -> tuple[float, float, float, float] | None:
    """Convert Docling point geometry to rendered-page pixel coordinates."""
    value = _bbox_dict(bbox)
    if not all(value.get(key) is not None for key in ("l", "t", "r", "b")):
        return None
    left, top, right, bottom = (float(value[key]) for key in ("l", "t", "r", "b"))
    page_width = float(page_record["page_width_pt"])
    page_height = float(page_record["page_height_pt"])
    image_width = int(page_record["image_width_px"])
    image_height = int(page_record["image_height_px"])
    x0, x1 = min(left, right), max(left, right)
    if str(value.get("coord_origin", "TOPLEFT")).upper() == "BOTTOMLEFT":
        y0, y1 = page_height - max(top, bottom), page_height - min(top, bottom)
    else:
        y0, y1 = min(top, bottom), max(top, bottom)
    return clip_bbox(
        (
            x0 * image_width / max(page_width, 1e-9),
            y0 * image_height / max(page_height, 1e-9),
            x1 * image_width / max(page_width, 1e-9),
            y1 * image_height / max(page_height, 1e-9),
        ),
        image_width,
        image_height,
    )


def iter_docling_items(
    document: Any, raw_document: Mapping[str, Any]
) -> Iterable[tuple[Any, Any, int]]:
    """Yield document items in the production backend order."""
    if hasattr(document, "iterate_items"):
        for order, pair in enumerate(document.iterate_items()):
            if isinstance(pair, tuple):
                yield pair[0], pair[1] if len(pair) > 1 else None, order
            else:
                yield pair, None, order
        return
    order = 0
    for key in (
        "texts",
        "tables",
        "pictures",
        "groups",
        "key_value_items",
        "form_items",
    ):
        for item in raw_document.get(key, []) or []:
            yield item, None, order
            order += 1


def _resolve_page_number(
    page_number: int, page_map: Mapping[int, Any], page_start: int
) -> int | None:
    if page_number in page_map:
        return page_number
    shifted = page_start + page_number - 1
    return shifted if shifted in page_map else None


def convert_docling_document(
    document: Any,
    raw_document: Mapping[str, Any],
    page_records: list[dict[str, Any]],
    *,
    document_id: str,
    pdf_hash: str,
    page_start: int,
) -> RegionConversionResult:
    """Convert one Docling document with production-compatible output fields."""
    page_map = {int(page["page_number"]): page for page in page_records}
    regions: list[LayoutRegion] = []
    item_count = provenance_count = skipped_page_count = skipped_geometry_count = 0
    for item, _level, doc_order in iter_docling_items(document, raw_document):
        item_count += 1
        label = _enum_text(_value(item, "label", "unknown")).lower()
        text = _value(item, "text")
        orig = _value(item, "orig")
        self_ref = _value(item, "self_ref")
        content_layer = _enum_text(_value(item, "content_layer"))
        for provenance_index, provenance in enumerate(_value(item, "prov", []) or []):
            provenance_count += 1
            page_number = _resolve_page_number(
                int(_value(provenance, "page_no", -1)), page_map, page_start
            )
            if page_number is None:
                skipped_page_count += 1
                continue
            bbox = _value(provenance, "bbox")
            bbox_px = docling_bbox_to_px(bbox, page_map[page_number])
            if bbox_px is None or bbox_area(bbox_px) <= 0:
                skipped_geometry_count += 1
                continue
            x0, y0, x1, y1 = bbox_px
            region = {
                "doc_id": document_id,
                "pdf_hash": pdf_hash,
                "layout_region_id": f"p{page_number:04d}_d{doc_order:06d}_{provenance_index:02d}",
                "page_number": page_number,
                "region_index": len(
                    [r for r in regions if r["docling_doc_order"] == doc_order]
                ),
                "docling_doc_order": doc_order,
                "docling_reading_order": None,
                "visual_overlay_order": None,
                "layout_reading_order": None,
                "included_in_layout_reading_order": None,
                "reading_order_column": None,
                "reading_order_band": None,
                "reading_order_role": None,
                "reading_order_excluded_reason": None,
                "docling_self_ref": str(self_ref) if self_ref is not None else None,
                "docling_label": label,
                "type": docling_label_to_region_type(label),
                "content_layer": content_layer,
                "text": text if isinstance(text, str) else None,
                "orig": orig if isinstance(orig, str) else None,
                "score": None,
                "bbox_px": [float(x0), float(y0), float(x1), float(y1)],
                "bbox_docling": _bbox_dict(bbox),
                "width_px": float(x1 - x0),
                "height_px": float(y1 - y0),
                "area_px": float(bbox_area(bbox_px)),
                "source": "docling",
            }
            initialize_region_schema(region, page_record=page_map[page_number])
            region["source_coordinate_space"] = {
                "units": "pt",
                "origin": (
                    "bottom_left"
                    if "bottom" in str(_bbox_dict(bbox).get("coord_origin", "TOPLEFT")).lower()
                    else "top_left"
                ),
            }
            regions.append(region)
    return RegionConversionResult(
        regions,
        item_count,
        provenance_count,
        skipped_page_count,
        skipped_geometry_count,
    )


def convert_docling_items(
    raw_document: dict[str, Any], pages: PageSet
) -> list[LayoutRegion]:
    """Compatibility wrapper for callers of the former serialized-only helper."""
    document = pages.document
    page_records = [
        {
            "page_number": page.page_number,
            "page_width_pt": page.width_pt,
            "page_height_pt": page.height_pt,
            "image_width_px": page.width_px,
            "image_height_px": page.height_px,
        }
        for page in pages.pages
    ]
    return convert_docling_document(
        raw_document,
        raw_document,
        page_records,
        document_id=document.doc_id,
        pdf_hash=document.pdf_hash,
        page_start=document.page_start,
    ).regions
