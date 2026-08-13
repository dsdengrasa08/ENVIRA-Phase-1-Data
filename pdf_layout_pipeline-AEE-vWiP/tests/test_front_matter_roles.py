from types import SimpleNamespace

from envira_pdf_layout.config import Page1FilterConfig
from envira_pdf_layout.filtering.front_matter_roles import (
    classify_page1_front_matter_roles,
)


def region(identifier, text, x0, y0, x1, y1, typ="Text", label="text"):
    return {
        "layout_region_id": identifier,
        "page_number": 1,
        "text": text,
        "type": typ,
        "docling_label": label,
        "bbox_px": [x0, y0, x1, y1],
    }


def test_classifies_history_group_and_legal_notice_before_body():
    pages = {1: SimpleNamespace(width_px=1000, height_px=1000)}
    rows = [
        region("abstract", "Abstract", 100, 300, 300, 325, "Section-header", "section_header"),
        region("abstract-body", "This study examines a scientific question in sufficient detail. It reports observations and conclusions.", 100, 330, 800, 410),
        region("history-heading", "Manuscript record", 40, 430, 280, 450),
        region("history", "Submitted 12 January 2024; revised 2 February 2024; accepted 7 March 2024", 40, 455, 300, 490),
        region("legal", "Copyright 2024 by the publishing organization. Licensed for distribution.", 100, 505, 700, 530),
        region("intro", "1 Introduction", 100, 550, 350, 575, "Section-header", "section_header"),
        region("body", "The experiment was accepted by the review committee in 2020 and the organization supplied samples.", 100, 585, 800, 650),
    ]
    result = classify_page1_front_matter_roles(rows, pages, Page1FilterConfig())
    excluded = {row["layout_region_id"]: row for row in result.excluded}
    assert set(excluded) == {"history-heading", "history", "legal"}
    assert excluded["history"]["document_role"] == "article_history"
    assert excluded["legal"]["document_role"] == "publisher_legal"
    assert {row["layout_region_id"] for row in result.kept} >= {"abstract-body", "intro", "body"}


def test_retains_ambiguous_scientific_prose_and_protected_classes():
    pages = {1: SimpleNamespace(width_px=1000, height_px=1000)}
    prose = "Copyright licensing was examined in the experiment because redistribution policies affect access to all archived samples. The analysis includes several organizations."
    rows = [
        region("prose", prose, 100, 400, 800, 500),
        region("caption", "Copyright status by experimental year", 100, 510, 500, 535, "Caption", "caption"),
    ]
    result = classify_page1_front_matter_roles(rows, pages, Page1FilterConfig())
    assert result.excluded == []
    assert {row["layout_region_id"] for row in result.kept} == {"prose", "caption"}


def test_unknown_structure_keeps_weak_date_metadata():
    pages = {1: SimpleNamespace(width_px=1000, height_px=1000)}
    rows = [region("weak", "Received samples 2024", 100, 400, 400, 430)]
    result = classify_page1_front_matter_roles(rows, pages, Page1FilterConfig())
    assert result.excluded == []
