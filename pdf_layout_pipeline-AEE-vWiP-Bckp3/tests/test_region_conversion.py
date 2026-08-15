from dataclasses import dataclass

from envira_pdf_layout.region_conversion import (
    convert_docling_document,
    docling_bbox_to_px,
    docling_label_to_region_type,
)


PAGES = [
    {
        "page_number": 3,
        "page_width_pt": 100.0,
        "page_height_pt": 200.0,
        "image_width_px": 200,
        "image_height_px": 400,
    }
]


@dataclass
class BBox:
    l: float  # noqa: E741 - Docling's public bounding-box field is named ``l``.
    t: float
    r: float
    b: float
    coord_origin: str = "TOPLEFT"


@dataclass
class Provenance:
    page_no: int
    bbox: BBox | None
    orientation: float | None = None


@dataclass
class Item:
    label: str
    prov: list[Provenance]
    text: str = "example"
    orig: str = "original"
    self_ref: str = "#/texts/0"
    content_layer: str = "body"


class Document:
    def __init__(self, items):
        self.items = items

    def iterate_items(self):
        return [(item, 0) for item in self.items]


def convert(document, raw=None):
    return convert_docling_document(
        document,
        raw or {},
        PAGES,
        document_id="doc",
        pdf_hash="hash",
        page_start=3,
    )


def test_label_mapping_preserves_future_labels_readably():
    assert docling_label_to_region_type("section_header") == "Section-header"
    assert docling_label_to_region_type("picture") == "Figure"
    assert docling_label_to_region_type("document_index") == "Table"
    assert docling_label_to_region_type("new_label") == "New-Label"


def test_object_conversion_preserves_production_schema_and_relative_page_mapping():
    result = convert(
        Document(
            [
                Item(
                    "text",
                    [
                        Provenance(1, BBox(10, 20, 50, 40)),
                        Provenance(1, BBox(10, 50, 50, 70)),
                    ],
                )
            ]
        )
    )
    assert result.item_count == 1
    assert result.provenance_count == 2
    assert [region["layout_region_id"] for region in result.regions] == [
        "p0003_d000000_00",
        "p0003_d000000_01",
    ]
    assert [region["region_index"] for region in result.regions] == [0, 1]
    expected_legacy_fields = {
        "doc_id": "doc",
        "pdf_hash": "hash",
        "layout_region_id": "p0003_d000000_00",
        "page_number": 3,
        "region_index": 0,
        "docling_doc_order": 0,
        "docling_reading_order": None,
        "visual_overlay_order": None,
        "layout_reading_order": None,
        "included_in_layout_reading_order": None,
        "reading_order_column": None,
        "reading_order_band": None,
        "reading_order_role": None,
        "reading_order_excluded_reason": None,
        "docling_self_ref": "#/texts/0",
        "docling_label": "text",
        "type": "Text",
        "content_layer": "body",
        "text": "example",
        "orig": "original",
        "score": None,
        "bbox_px": [20.0, 40.0, 100.0, 80.0],
        "bbox_docling": {
            "l": 10,
            "t": 20,
            "r": 50,
            "b": 40,
            "coord_origin": "TOPLEFT",
        },
        "width_px": 80.0,
        "height_px": 40.0,
        "area_px": 3200.0,
        "source": "docling",
    }
    region = result.regions[0]
    assert {key: region[key] for key in expected_legacy_fields} == expected_legacy_fields
    assert region["region_schema_version"] == 1
    assert region["bbox_px"] == region["resolved_bbox_px"] == region["physical_bbox_px"]
    assert region["geometry_version"] == 1
    assert region["coordinate_space"]["units"] == "px"


def test_serialized_fallback_uses_established_list_order():
    raw = {
        "texts": [
            {
                "label": "text",
                "text": "first",
                "prov": [{"page_no": 3, "bbox": {"l": 0, "t": 0, "r": 10, "b": 10}}],
            }
        ],
        "tables": [
            {
                "label": "table",
                "prov": [{"page_no": 3, "bbox": {"l": 0, "t": 20, "r": 10, "b": 30}}],
            }
        ],
    }
    result = convert(raw, raw)
    assert [region["docling_doc_order"] for region in result.regions] == [0, 1]
    assert [region["type"] for region in result.regions] == ["Text", "Table"]


def test_invalid_page_and_geometry_are_skipped_and_accounted_for():
    result = convert(
        Document(
            [
                Item("text", [Provenance(99, BBox(0, 0, 10, 10))]),
                Item("text", [Provenance(3, None)]),
                Item("text", [Provenance(3, BBox(4, 4, 4, 4))]),
            ]
        )
    )
    assert result.regions == []
    assert result.skipped_page_count == 1
    assert result.skipped_geometry_count == 2


def test_bottom_left_bbox_is_normalized_and_clipped():
    assert docling_bbox_to_px(
        BBox(-10, 10, 110, 30, "BOTTOMLEFT"), PAGES[0]
    ) == (0.0, 340.0, 200.0, 380.0)


def test_upstream_orientation_is_preserved_in_region_contract():
    result = convert(
        Document([Item("caption", [Provenance(3, BBox(10, 20, 20, 100), 270)])])
    )
    assert result.regions[0]["orientation"] == {
        "angle_degrees": 270.0,
        "confidence": 1.0,
        "source": "docling_provenance",
    }
