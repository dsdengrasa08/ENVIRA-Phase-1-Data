from types import SimpleNamespace
from envira_pdf_layout.config import FooterFilterConfig, HeaderFilterConfig
from envira_pdf_layout.filtering.footer_furniture import (
    filter_repeated_footer_furniture,
)
from envira_pdf_layout.filtering.headers import filter_later_page_headers


def region(i, page, text, y0, y1, typ="Text"):
    return {
        "layout_region_id": i,
        "page_number": page,
        "text": text,
        "type": typ,
        "bbox_px": [10, y0, 150, y1],
        "docling_label": "text",
    }


def test_recurring_header_and_footer():
    pages = {i: SimpleNamespace(width_px=1000, height_px=1000) for i in range(1, 4)}
    rows = [
        region("h2", 2, "Journal 2024", 10, 30),
        region("h3", 3, "Journal 2025", 10, 30),
        region("f2", 2, "Publisher", 930, 950),
        region("f3", 3, "Publisher", 930, 950),
    ]
    header = filter_later_page_headers(rows, pages, HeaderFilterConfig())
    assert {r["layout_region_id"] for r in header.excluded} == {"h2", "h3"}
    footer = filter_repeated_footer_furniture(header.kept, pages, FooterFilterConfig())
    assert {r["layout_region_id"] for r in footer.excluded} == {"f2", "f3"}
