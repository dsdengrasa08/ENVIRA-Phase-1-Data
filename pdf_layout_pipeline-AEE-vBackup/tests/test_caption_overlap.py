from copy import deepcopy

from envira_pdf_layout.caption_overlap import (
    build_caption_groups,
    overlap_features,
    resolve_caption_overlaps,
)

PAGES = [{"page_number": 1, "image_width_px": 1000, "image_height_px": 1000}]


def region(region_id, typ, bbox, text="", order=1, score=None):
    return {
        "layout_region_id": region_id,
        "page_number": 1,
        "type": typ,
        "docling_label": typ.lower(),
        "bbox_px": bbox,
        "text": text,
        "layout_reading_order": order,
        "score": score,
    }


def test_overlap_features_distinguish_iou_and_directional_containment():
    small = region("small", "Caption", [100, 100, 200, 130], "Table 1")
    large = region("large", "Caption", [90, 90, 700, 180], "Table 1. Results")
    features = overlap_features(small, large, PAGES[0])
    assert features["a_containment"] == 1.0
    assert features["b_containment"] < 0.1
    assert features["iou"] < 0.1
    assert features["text_relation"] == "a_in_b"


def test_clear_duplicate_collapses_without_mutating_raw_regions():
    raw = [
        region("a", "Caption", [100, 100, 700, 150], "Table 1. Results", score=0.8),
        region("b", "Caption", [101, 100, 699, 151], "Table 1. Results", score=0.9),
    ]
    before = deepcopy(raw)
    resolved, relationships, suppressed = resolve_caption_overlaps(raw, PAGES)
    assert raw == before
    assert [r["layout_region_id"] for r in resolved] == ["b"]
    assert resolved[0]["source_region_ids"] == ["b", "a"]
    assert [r["layout_region_id"] for r in suppressed] == ["a"]
    assert relationships[0]["kind"] == "DUPLICATE"
    assert relationships[0]["status"] == "collapsed"


def test_nested_identifier_is_preserved_not_suppressed():
    raw = [
        region("id", "Caption", [100, 100, 220, 130], "Table S7"),
        region("caption", "Caption", [90, 90, 700, 180], "Table S7. Outcomes by group"),
    ]
    resolved, relationships, suppressed = resolve_caption_overlaps(raw, PAGES)
    assert {r["layout_region_id"] for r in resolved} == {"id", "caption"}
    assert suppressed == []
    assert relationships[0]["kind"] == "NESTED_COMPONENT"


def test_overlapping_unique_caption_fragments_are_grouped_not_suppressed():
    raw = [
        region("first", "Caption", [100, 100, 700, 145], "Table 4. First line", 1),
        region("second", "Caption", [100, 140, 700, 190], "continued measurements", 2),
    ]
    resolved, relationships, suppressed = resolve_caption_overlaps(raw, PAGES)
    assert len(resolved) == 2
    assert suppressed == []
    assert relationships[0]["kind"] == "COMPLEMENTARY_FRAGMENT"


def test_context_group_preserves_identifier_and_deduplicates_emission_membership():
    regions = [
        region("id", "Caption", [100, 100, 220, 130], "Table 2", 1),
        region("caption", "Caption", [90, 90, 700, 180], "Table 2. Values", 2),
        region("table", "Table", [90, 185, 700, 500], order=3),
    ]
    resolved, relationships, _ = resolve_caption_overlaps(regions, PAGES)
    resolved_by_id = {item["layout_region_id"]: item for item in resolved}
    assert resolved_by_id["id"]["emission_policy"] == "suppress_duplicate_text_emission"
    logical = [
        {
            "internal_id": "doc:p0001:t01",
            "page_number": 1,
            "table_region_id": "table",
            "identifier_region_ids": ["id", "caption"],
            "caption_region_ids": ["caption"],
        }
    ]
    group = build_caption_groups(resolved, logical, relationships, PAGES)[0]
    assert group["ordered_source_region_ids"] == ["id", "caption"]
    assert group["semantic_text_region_ids"] == ["caption"]
    assert group["text"] == "Table 2. Values"
    assert group["relationships"][0]["status"] == "preserved_as_nested_component"


def test_overlapping_caption_fragments_emit_one_deduplicated_caption_text():
    regions = [
        region(
            "first",
            "Caption",
            [100, 100, 700, 145],
            "Table 3. Stalk yield and CCS",
            1,
        ),
        region(
            "second",
            "Text",
            [100, 140, 700, 185],
            "CCS, sugar yield observed at three rates.",
            2,
        ),
        region("table", "Table", [100, 190, 700, 500], order=3),
    ]
    resolved, relationships, _ = resolve_caption_overlaps(regions, PAGES)
    logical = [
        {
            "internal_id": "doc:p0001:t01",
            "page_number": 1,
            "table_region_id": "table",
            "identifier_region_ids": ["first"],
            "caption_region_ids": ["first", "second"],
        }
    ]
    group = build_caption_groups(resolved, logical, relationships, PAGES)[0]
    assert group["semantic_text_region_ids"] == ["first", "second"]
    assert group["text"] == (
        "Table 3. Stalk yield and CCS sugar yield observed at three rates."
    )


def test_context_group_links_caption_fragments_separated_by_small_gap():
    regions = [
        region("first", "Caption", [100, 100, 700, 130], "First caption line", 1),
        region("second", "Caption", [100, 135, 700, 165], "Second caption line", 2),
        region("table", "Table", [100, 170, 700, 500], order=3),
    ]
    resolved, relationships, _ = resolve_caption_overlaps(regions, PAGES)
    logical = [
        {
            "internal_id": "doc:p0001:t01",
            "page_number": 1,
            "table_region_id": "table",
            "identifier_region_ids": [],
            "caption_region_ids": ["first", "second"],
        }
    ]
    group = build_caption_groups(resolved, logical, relationships, PAGES)[0]
    assert group["relationships"][0]["kind"] == "COMPLEMENTARY_FRAGMENT"
    assert group["relationships"][0]["status"] == "grouped"


def test_caption_table_overlap_is_recorded_without_geometry_changes():
    raw = [
        region("caption", "Caption", [100, 100, 700, 205], "Results", 1),
        region("table", "Table", [100, 200, 700, 500], order=2),
    ]
    before = deepcopy(raw)
    resolved, relationships, _ = resolve_caption_overlaps(raw, PAGES)
    assert raw == before
    assert next(r for r in resolved if r["type"] == "Table")["bbox_px"] == [
        100,
        200,
        700,
        500,
    ]
    assert relationships[0]["kind"] == "BOUNDARY_TOUCH"


def test_cross_type_equal_text_duplicate_is_canonicalized():
    raw = [
        region("caption", "Caption", [100, 100, 700, 150], "Table 5. Yield"),
        region("text", "Text", [101, 100, 699, 151], "Table 5. Yield", score=0.9),
    ]
    resolved, relationships, suppressed = resolve_caption_overlaps(raw, PAGES)
    assert len(resolved) == 1
    assert relationships[0]["kind"] == "DUPLICATE"
    assert len(suppressed) == 1


def test_contained_unique_caption_text_is_fragment_not_nested():
    raw = [
        region("merged", "Caption", [100, 100, 800, 180], "Table 5. Stalk yield"),
        region("line", "Text", [110, 140, 790, 175], "observed at three rates"),
    ]
    resolved, relationships, suppressed = resolve_caption_overlaps(raw, PAGES)
    assert len(resolved) == 2
    assert suppressed == []
    assert relationships[0]["kind"] == "COMPLEMENTARY_FRAGMENT"


def test_non_caption_table_note_overlap_is_analyzed():
    raw = [
        region("table", "Table", [100, 200, 700, 500]),
        region("note", "Footnote", [100, 495, 700, 530], "* p < .05"),
    ]
    _, relationships, _ = resolve_caption_overlaps(raw, PAGES)
    assert relationships[0]["kind"] in {
        "BOUNDARY_TOUCH",
        "CROSS_ROLE_BOUNDARY_OVERLAP",
    }


def test_duplicate_chain_has_one_canonical_and_contiguous_resolved_order():
    raw = [
        region("a", "Caption", [100, 100, 700, 150], "Table 1", order=1),
        region("b", "Caption", [101, 100, 699, 151], "Table 1", order=2),
        region("c", "Caption", [102, 100, 698, 152], "Table 1", order=3),
        region("table", "Table", [100, 160, 700, 500], order=4),
    ]
    resolved, _, suppressed = resolve_caption_overlaps(raw, PAGES)
    assert len(suppressed) == 2
    assert (
        len({r["source_region_ids"][0] for r in resolved if r["type"] == "Caption"})
        == 1
    )
    assert [r["resolved_reading_order"] for r in resolved] == [1, 2]


def test_caption_group_exposes_parent_union_and_provenance_children():
    regions = [
        region("label", "Caption", [100, 100, 220, 130], "Table 2.", 1),
        region("description", "Text", [100, 135, 700, 165], "Measured outcomes", 2),
        region("table", "Table", [100, 170, 700, 500], order=3),
    ]
    logical = [
        {
            "internal_id": "table-1",
            "page_number": 1,
            "table_region_id": "table",
            "identifier_region_ids": ["label"],
            "caption_region_ids": ["description"],
        }
    ]

    group = build_caption_groups(regions, logical, [], PAGES)[0]

    assert group["type"] == "Table Caption"
    assert group["bbox_px"] == [100.0, 100.0, 700.0, 165.0]
    assert group["text"] == "Table 2. Measured outcomes"
    assert [child["semantic_role"] for child in group["children"]] == [
        "table_caption_identifier",
        "table_caption_fragment",
    ]
    assert [child["source_type"] for child in group["children"]] == ["Caption", "Text"]
    assert [child["source_bbox_px"] for child in group["children"]] == [
        [100, 100, 220, 130],
        [100, 135, 700, 165],
    ]
