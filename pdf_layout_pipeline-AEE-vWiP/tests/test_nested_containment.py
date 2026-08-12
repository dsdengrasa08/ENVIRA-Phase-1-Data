from copy import deepcopy

from envira_pdf_layout.nested_containment import (
    analyze_nested_containment,
    resolve_nested_hierarchy,
    validate_hierarchy,
)


def region(region_id, typ, bbox, *, page=1, text="", order=0, **extra):
    return {
        "layout_region_id": region_id,
        "page_number": page,
        "type": typ,
        "docling_label": typ.lower(),
        "bbox_px": bbox,
        "text": text,
        "layout_reading_order": order,
        "docling_doc_order": order,
        **extra,
    }


def test_analysis_is_non_destructive_and_records_geometry_and_prior_behavior():
    regions = [
        region("figure", "Figure", [0, 0, 500, 500]),
        region("formula", "Formula", [20, 20, 100, 80], text="x"),
    ]
    before = deepcopy(regions)
    proposals = analyze_nested_containment(regions)
    assert regions == before
    assert proposals[0]["previous_behavior"] == "would_have_been_excluded"
    assert proposals[0]["features"]["child_coverage"] == 1
    assert proposals[0]["features"]["child_text_bearing"] is True


def test_compatible_asset_child_is_nested_and_ordered_after_hierarchy():
    result = resolve_nested_hierarchy(
        [
            region("figure", "Figure", [0, 0, 500, 500], order=0),
            region("b", "Formula", [100, 100, 150, 150], order=1),
            region("a", "Formula", [20, 20, 50, 50], order=2),
            region("body", "Text", [600, 10, 900, 100], order=3),
        ]
    )
    assert result.diagnostics["valid"]
    assert [r["layout_region_id"] for r in result.top_level_regions] == [
        "figure",
        "body",
    ]
    assert [r["layout_region_id"] for r in result.nested_regions] == ["b", "a"]
    by_id = {r["layout_region_id"]: r for r in result.regions}
    assert by_id["figure"]["nested_child_region_ids"] == ["a", "b"]
    assert by_id["a"]["parent_local_reading_order"] == 1
    assert by_id["b"]["parent_local_reading_order"] == 2
    assert by_id["figure"]["resolved_reading_order"] == 1
    assert by_id["body"]["resolved_reading_order"] == 2


def test_expanded_figure_capturing_text_remains_top_level_and_ambiguous():
    result = resolve_nested_hierarchy(
        [
            region(
                "figure",
                "Figure",
                [0, 0, 500, 500],
                figure_completion_original_bbox_px=[0, 0, 200, 200],
            ),
            region("body", "Text", [300, 300, 450, 350], text="valid body"),
        ]
    )
    assert result.nested_regions == []
    assert len(result.top_level_regions) == 2
    assert result.decisions[0]["kind"] == "AMBIGUOUS_CONTAINMENT"
    assert result.decisions[0]["reason"] == "expanded_asset_captures_text"


def test_nested_container_and_multiple_parents_are_not_forced_into_hierarchy():
    regions = [
        region("figure", "Figure", [0, 0, 500, 500]),
        region("table", "Table", [0, 0, 500, 500]),
        region("text", "Text", [10, 10, 50, 50]),
    ]
    result = resolve_nested_hierarchy(regions)
    assert result.nested_regions == []
    assert any(d["reason"] == "multiple_plausible_parents" for d in result.decisions)
    assert all(r["emission_policy"] == "emit_canonical" for r in result.regions)


def test_cross_page_missing_reference_and_integrity_errors_are_reported():
    regions = [
        region("figure", "Figure", [0, 0, 500, 500], page=1),
        region("text", "Text", [10, 10, 50, 50], page=2),
    ]
    proposals = [
        {
            "proposal_id": "bad",
            "page_number": 1,
            "parent_region_id": "figure",
            "child_region_id": "text",
            "parent_type": "Figure",
            "child_type": "Text",
            "features": {},
            "previous_behavior": "would_have_been_excluded",
        }
    ]
    result = resolve_nested_hierarchy(regions, proposals)
    assert result.decisions[0]["reason"] == "cross_page_hierarchy"
    assert validate_hierarchy(regions + [regions[0]], [])["valid"] is False


def test_valid_partition_has_no_missing_or_duplicate_ids():
    result = resolve_nested_hierarchy(
        [
            region("table", "Table", [0, 0, 500, 500]),
            region("note", "Footnote", [10, 400, 490, 450]),
            region("outside", "Text", [600, 0, 800, 80]),
        ]
    )
    all_ids = {r["layout_region_id"] for r in result.regions}
    partition = {r["layout_region_id"] for r in result.top_level_regions} | {
        r["layout_region_id"] for r in result.nested_regions
    }
    assert all_ids == partition
    assert not (
        {r["layout_region_id"] for r in result.top_level_regions}
        & {r["layout_region_id"] for r in result.nested_regions}
    )
