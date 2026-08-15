from envira_pdf_layout.caption_association import (
    associate_captions,
    parse_caption_reference,
)
from envira_pdf_layout.config import CaptionAssociationConfig

PAGES = [{"page_number": 1, "image_width_px": 1000, "image_height_px": 1000}]


def region(region_id, typ, bbox, text=""):
    return {
        "layout_region_id": region_id,
        "page_number": 1,
        "type": typ,
        "bbox_px": bbox,
        "text": text,
        "reading_order_column": "single",
    }


def test_reference_parser_supports_supplements_and_letter_identifiers():
    reference = parse_caption_reference("Supplementary Figure A. Architecture")
    assert reference is not None
    assert reference.kind == "figure"
    assert reference.number == "A"


def test_disabled_stage_returns_no_relationships():
    relationships = associate_captions(
        [
            region("figure", "Figure", [100, 100, 400, 300]),
            region("caption", "Caption", [100, 305, 400, 340], "Figure 1. Test"),
        ],
        PAGES,
        config=CaptionAssociationConfig(enabled=False),
    )
    assert relationships == []


def test_acceptance_threshold_prevents_weak_ownership():
    relationships = associate_captions(
        [
            region("figure", "Figure", [100, 100, 400, 300]),
            region("caption", "Caption", [350, 390, 650, 430], "unlabelled"),
        ],
        PAGES,
        config=CaptionAssociationConfig(acceptance_score=0.9),
    )
    assert relationships[0]["status"] == "no_compatible_parent"


def test_input_order_does_not_change_ambiguous_outcome():
    caption = region("caption", "Caption", [100, 305, 900, 340], "unlabelled")
    parents = [
        region("left", "Figure", [100, 100, 450, 300]),
        region("right", "Figure", [550, 100, 900, 300]),
    ]
    forward = associate_captions(parents + [caption], PAGES)
    reverse = associate_captions(list(reversed(parents)) + [caption], PAGES)
    assert forward == reverse
    assert forward[0]["status"] == "unresolved_conflict"


def test_association_exposes_deterministic_work_counters():
    metrics = {}
    associate_captions(
        [
            region("figure", "Figure", [100, 100, 400, 300]),
            region("caption", "Caption", [100, 305, 400, 340], "Figure 1. Test"),
        ],
        PAGES,
        metrics=metrics,
    )
    assert metrics == {
        "caption_candidates": 1,
        "parent_pairs_considered": 1,
        "pairs_scored": 1,
        "blocker_queries": 1,
    }


def test_metadata_heading_caption_is_not_assigned_to_an_asset():
    heading = region("heading", "Caption", [100, 305, 400, 340], "DOCUMENT DATA")
    heading["semantic_role"] = "metadata_container_heading"

    relationships = associate_captions(
        [region("figure", "Figure", [100, 100, 400, 300]), heading], PAGES
    )

    assert relationships == []


def test_note_derived_table_letter_is_not_assigned_as_caption():
    relationships = associate_captions(
        [
            region("table", "Table", [100, 100, 700, 500]),
            region(
                "note",
                "Caption",
                [100, 505, 700, 540],
                "Table a See Table 2 for treatment codes.",
            ),
        ],
        PAGES,
    )
    assert relationships == []
