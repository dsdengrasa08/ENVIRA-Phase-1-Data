from types import SimpleNamespace
from envira_pdf_layout.config import ReadingOrderConfig
from envira_pdf_layout.reading_order import assign_document_reading_order


def test_two_column_order():
    page = SimpleNamespace(width_px=1000, height_px=1000)
    regions = [
        {
            "layout_region_id": "r",
            "page_number": 1,
            "bbox_px": [x, y, x + 300, y + 50],
            "width_px": 300,
        }
        for x, y in [(600, 50), (50, 100), (600, 100), (50, 50)]
    ]
    ordered, meta = assign_document_reading_order(
        regions, {1: page}, ReadingOrderConfig()
    )
    assert [r["bbox_px"][:2] for r in ordered] == [
        [50, 50],
        [50, 100],
        [600, 50],
        [600, 100],
    ]
    assert meta["1"]["numbered_region_count"] == 4
