from envira_pdf_layout.caption_validation import (
    CaptionLine,
    validate_and_segment_captions,
)
from envira_pdf_layout.table_context import associate_table_context


PAGES = [{"page_number": 1, "image_width_px": 1000, "image_height_px": 1200}]


def region(rid, kind, box, text="", lines=None):
    value = {
        "layout_region_id": rid,
        "page_number": 1,
        "type": kind,
        "text": text,
        "bbox_px": box,
        "layout_reading_order": 1,
    }
    if lines is not None:
        value["text_lines"] = [
            {"text": line_text, "bbox_px": line_box} for line_text, line_box in lines
        ]
    return value


def test_figure_then_table_caption_is_split_and_reassociated():
    regions = [
        region("figure", "Figure", [100, 100, 800, 400]),
        region(
            "caption",
            "Caption",
            [100, 405, 800, 510],
            "Figure 1. Result Table II. Measurements",
            [
                ("Figure 1. Result", [100, 405, 800, 445]),
                ("Table II. Measurements", [100, 465, 800, 505]),
            ],
        ),
        region("table", "Table", [100, 515, 800, 900]),
    ]
    resolved, decisions, associations = validate_and_segment_captions(regions, PAGES)
    segments = [item for item in resolved if item.get("derived_from_region_id")]
    assert [item["caption_object_type"] for item in segments] == ["Figure", "Table"]
    assert [item["bbox_px"] for item in segments] == [
        [100.0, 405.0, 800.0, 445.0],
        [100.0, 465.0, 800.0, 505.0],
    ]
    assert decisions[0]["action"] == "split"
    assert {item["parent_region_id"] for item in associations} == {"figure", "table"}
    assert all(
        item["features"]["source_region_id"] == "caption" for item in associations
    )
    tables = associate_table_context(resolved, PAGES, document_id="doc")
    assert segments[0]["layout_region_id"] not in tables[0]["caption_region_ids"]
    assert segments[1]["layout_region_id"] in tables[0]["caption_region_ids"]


def test_table_then_figure_and_same_type_consecutive_captions_are_supported():
    regions = [
        region("table", "Table", [100, 50, 800, 300]),
        region(
            "mixed",
            "Caption",
            [100, 305, 800, 420],
            lines=[
                ("Table A. Values", [100, 305, 800, 345]),
                ("Fig. IV. Comparison", [100, 375, 800, 415]),
            ],
        ),
        region("figure", "Figure", [100, 425, 800, 700]),
    ]
    resolved, decisions, _ = validate_and_segment_captions(regions, PAGES)
    assert decisions[0]["action"] == "split"
    assert [r["caption_identifier"] for r in resolved if "caption_identifier" in r] == [
        "Table A",
        "Fig. IV",
    ]


def test_mid_line_cross_references_do_not_split():
    for lines in (
        [
            (
                "Figure 3. Comparison of values reported in Table 2",
                [100, 405, 800, 445],
            ),
            ("under different experimental conditions.", [100, 450, 800, 490]),
        ],
        [
            (
                "Table 4. Results corresponding to Figure 5 and Figure 6.",
                [100, 305, 800, 345],
            )
        ],
    ):
        regions = [
            region("figure", "Figure", [100, 100, 800, 400]),
            region("caption", "Caption", [100, 405, 800, 490], lines=lines),
            region("table", "Table", [100, 500, 800, 900]),
        ]
        resolved, decisions, associations = validate_and_segment_captions(
            regions, PAGES
        )
        assert not any(item.get("derived_from_region_id") for item in resolved)
        assert decisions == []
        assert associations == []


def test_line_start_reference_without_distinct_parent_is_retained_as_ambiguous():
    regions = [
        region("figure", "Figure", [100, 100, 800, 400]),
        region(
            "caption",
            "Caption",
            [100, 405, 800, 500],
            lines=[
                ("Figure 3. Results from the experiment.", [100, 405, 800, 445]),
                ("Table 2 was used as the baseline.", [100, 450, 800, 490]),
            ],
        ),
    ]
    resolved, decisions, _ = validate_and_segment_captions(regions, PAGES)
    caption = next(item for item in resolved if item["layout_region_id"] == "caption")
    assert decisions[0]["action"] == "retain"
    assert caption["caption_validation_status"] in {"single", "ambiguous"}
    assert caption["bbox_px"] == [100, 405, 800, 500]


def test_identifier_and_description_formatting_remain_one_caption():
    regions = [
        region("figure", "Figure", [100, 100, 800, 400]),
        region(
            "caption",
            "Caption",
            [100, 405, 800, 490],
            lines=[
                ("Figure 7.", [100, 405, 220, 430]),
                ("A multi-line description continues here.", [100, 435, 800, 465]),
                ("and finishes on this line.", [100, 468, 800, 490]),
            ],
        ),
    ]
    resolved, decisions, _ = validate_and_segment_captions(regions, PAGES)
    assert len(resolved) == 2
    assert decisions == []


def test_structured_ocr_provider_is_selective_and_can_supply_split_geometry():
    calls = []

    def provider(candidate, page):
        calls.append((candidate["layout_region_id"], page["page_number"]))
        return [
            CaptionLine("Fig. 8. Plot", (100, 405, 800, 445), source="glm_ocr"),
            CaptionLine("Tab. 9. Values", (100, 465, 800, 505), source="glm_ocr"),
        ]

    regions = [
        region("figure", "Figure", [100, 100, 800, 400]),
        region("caption", "Caption", [100, 405, 800, 510]),
        region("table", "Table", [100, 515, 800, 900]),
    ]
    resolved, decisions, _ = validate_and_segment_captions(
        regions, PAGES, line_provider=provider
    )
    assert calls == [("caption", 1)]
    assert decisions[0]["action"] == "split"
    assert len([item for item in resolved if item.get("derived_from_region_id")]) == 2
