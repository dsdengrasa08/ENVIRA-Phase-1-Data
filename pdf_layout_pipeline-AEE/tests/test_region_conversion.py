from types import SimpleNamespace

from envira_pdf_layout.region_conversion import (
    convert_docling_items,
    docling_label_to_region_type,
)
from envira_pdf_layout.types import PageSet


def test_label_mapping():
    assert docling_label_to_region_type("section_header") == "Section-header"
    assert docling_label_to_region_type("picture") == "Figure"
    assert docling_label_to_region_type("new_label") == "Unknown"


def test_conversion_preserves_structured_lines_and_typography(tmp_path):
    page = SimpleNamespace(
        page_number=1,
        width_px=1000,
        height_px=1200,
        width_pt=500,
        height_pt=600,
        page_image_path=tmp_path / "page.png",
    )
    raw = {
        "label": "caption",
        "text": "Figure 1. Plot",
        "prov": [{"page_no": 1, "bbox": {"l": 50, "t": 200, "r": 400, "b": 240}}],
        "text_lines": [{"text": "Figure 1. Plot", "bbox_px": [100, 400, 800, 480]}],
        "typography": {"font_size": 9},
    }
    regions = convert_docling_items(raw, PageSet(SimpleNamespace(), [page]))
    assert regions[0]["text_lines"] == raw["text_lines"]
    assert regions[0]["typography"] == {"font_size": 9}
