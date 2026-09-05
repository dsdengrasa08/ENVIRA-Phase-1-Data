from copy import deepcopy

from envira_pdf_layout.nested_containment import (
    analyze_nested_containment,
    resolve_nested_hierarchy,
    validate_hierarchy,
)
from envira_pdf_layout.config import ContainmentConfig
from envira_pdf_layout.layout_overlap import resolve_layout_overlaps


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


def test_expanded_figure_owns_centered_text_as_internal_content():
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
    assert [row["layout_region_id"] for row in result.top_level_regions] == ["figure"]
    assert [row["layout_region_id"] for row in result.nested_regions] == ["body"]
    assert result.decisions[0]["kind"] == "NESTED_CHILD"
    assert result.decisions[0]["reason"] == "figure_owns_centered_text"


def test_text_already_in_original_figure_can_remain_an_internal_child():
    result = resolve_nested_hierarchy(
        [
            region(
                "figure",
                "Figure",
                [0, 0, 500, 500],
                figure_completion_original_bbox_px=[0, 0, 200, 200],
            ),
            region("label", "Text", [20, 20, 80, 40], text="axis"),
        ]
    )
    assert [row["layout_region_id"] for row in result.nested_regions] == ["label"]


def test_trusted_figure_owns_centered_generic_text():
    regions = [
        region("figure", "Figure", [0, 0, 600, 600]),
        region("label", "Text", [20, 20, 80, 40], text="axis"),
    ]
    observations = resolve_layout_overlaps(
        regions,
        [{"page_number": 1, "image_width_px": 1000, "image_height_px": 1000}],
        containment=ContainmentConfig(),
    )
    proposals = analyze_nested_containment(
        observations.regions, observations.relationships, config=ContainmentConfig()
    )
    result = resolve_nested_hierarchy(
        observations.regions, proposals, ContainmentConfig()
    )
    assert [row["layout_region_id"] for row in result.nested_regions] == ["label"]
    assert result.decisions[0]["reason"] == "figure_owns_centered_text"


def test_rotated_edge_label_flows_from_overlap_into_nested_figure_emission():
    regions = [
        region("axis", "Text", [105, 50, 120, 275], text="Seasonal emission"),
        region("figure", "Figure", [100, 120, 850, 530]),
    ]
    pages = [{"page_number": 1, "image_width_px": 1000, "image_height_px": 1000}]
    observations = resolve_layout_overlaps(
        regions, pages, containment=ContainmentConfig()
    )
    proposals = analyze_nested_containment(
        observations.regions, observations.relationships, config=ContainmentConfig()
    )
    result = resolve_nested_hierarchy(
        observations.regions, proposals, ContainmentConfig()
    )

    assert [row["layout_region_id"] for row in result.top_level_regions] == ["figure"]
    assert [row["layout_region_id"] for row in result.nested_regions] == ["axis"]
    assert result.nested_regions[0]["emission_policy"] == "emit_as_nested_child"


def test_near_identical_text_envelope_is_nested_under_figure_not_score_competed():
    regions = [
        region("figure", "Figure", [100, 100, 800, 700], score=0.70),
        region("text", "Text", [101, 101, 799, 699], text="OCR", score=0.99),
    ]
    pages = [{"page_number": 1, "image_width_px": 1000, "image_height_px": 1000}]
    observations = resolve_layout_overlaps(
        regions, pages, containment=ContainmentConfig()
    )
    proposals = analyze_nested_containment(
        observations.regions, observations.relationships, config=ContainmentConfig()
    )
    result = resolve_nested_hierarchy(
        observations.regions, proposals, ContainmentConfig()
    )

    assert [row["layout_region_id"] for row in result.top_level_regions] == ["figure"]
    assert [row["layout_region_id"] for row in result.nested_regions] == ["text"]



def test_page_spanning_figure_is_not_trusted_to_own_contained_text():
    regions = [
        region("figure", "Figure", [0, 0, 900, 900]),
        region("label", "Text", [20, 20, 80, 40], text="axis"),
    ]
    observations = resolve_layout_overlaps(
        regions,
        [{"page_number": 1, "image_width_px": 1000, "image_height_px": 1000}],
        containment=ContainmentConfig(),
    )
    proposals = analyze_nested_containment(
        observations.regions, observations.relationships, config=ContainmentConfig()
    )
    result = resolve_nested_hierarchy(
        observations.regions, proposals, ContainmentConfig()
    )
    assert result.nested_regions == []
    assert result.decisions[0]["reason"] == "figure_exceeds_trusted_page_area"




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


def outcome(parent_type, child_type, child_text="x", **child_extra):
    parent = region("parent", parent_type, [0, 0, 500, 500])
    child = region(
        "child", child_type, [10, 10, 100, 60], text=child_text, **child_extra
    )
    return resolve_nested_hierarchy([parent, child])


def test_single_unknown_parent_is_ambiguous_without_child_count_exception():
    result = outcome("Unknown", "Text", "short")
    assert result.decisions[0]["kind"] == "AMBIGUOUS_CONTAINMENT"
    assert result.nested_regions == []
    assert len(result.top_level_regions) == 2


def test_text_containment_uses_text_outcomes_not_hierarchy():
    duplicate = outcome("Text", "Text", "same")
    duplicate.regions[0]["text"] = "same"
    # Re-run with matching parent text; geometric containment is not semantic hierarchy.
    duplicate = resolve_nested_hierarchy(
        [
            region("parent", "Text", [0, 0, 500, 500], text="same"),
            region("child", "Text", [10, 10, 100, 60], text="same"),
        ]
    )
    assert duplicate.decisions[0]["kind"] == "DUPLICATE"
    assert duplicate.nested_regions == []
    ambiguous = outcome("Text", "Text", "different paragraph")
    assert ambiguous.decisions[0]["kind"] == "AMBIGUOUS_TEXT_OCCLUSION"
    heading = resolve_nested_hierarchy(
        [
            region("parent", "Section-header", [0, 0, 500, 500], text="Methods"),
            region("child", "Text", [10, 10, 100, 60], text="body"),
        ]
    )
    assert heading.decisions[0]["kind"] == "INVALID_OCCLUSION"


def test_caption_identifier_fragment_is_not_container_hierarchy():
    result = resolve_nested_hierarchy(
        [
            region(
                "caption", "Caption", [0, 0, 500, 100], text="Figure 1. Description"
            ),
            region("identifier", "Text", [5, 5, 80, 30], text="Figure 1."),
        ]
    )
    assert result.decisions[0]["kind"] == "IDENTIFIER_FRAGMENT"
    assert result.nested_regions == []


def test_compatibility_matrix_for_supported_containers():
    cases = [
        ("Figure", "Formula", "x", "formula"),
        ("Figure", "Text", "A", "panel_label"),
        ("Table", "Text", "cell", "table_cell_text"),
        ("Table", "Formula", "x", "formula"),
        ("List", "Text", "item", "list_text"),
        ("Form", "Field-value", "value", "form_field"),
        ("Key-value", "Field-key", "name", "form_field"),
    ]
    for parent_type, child_type, text, role in cases:
        result = outcome(parent_type, child_type, text)
        assert result.decisions[0]["kind"] == "NESTED_CHILD"
        assert result.decisions[0]["inferred_child_role"] == role
        assert result.decisions[0]["role_evidence"]
        assert result.decisions[0]["policy_rule"].startswith(f"{parent_type}:{role}:")


def test_incompatible_and_ambiguous_asset_children_remain_top_level():
    assert outcome("Figure", "Table").decisions[0]["kind"] == "INVALID_OCCLUSION"
    assert outcome("Table", "Figure").decisions[0]["kind"] == "INVALID_OCCLUSION"
    full_caption = outcome(
        "Figure", "Caption", "Figure 1. A complete descriptive caption"
    )
    assert full_caption.decisions[0]["kind"] == "AMBIGUOUS_CONTAINMENT"
    paragraph = outcome("Figure", "Text", "x" * 100)
    assert paragraph.decisions[0]["kind"] == "NESTED_CHILD"
    assert [row["layout_region_id"] for row in paragraph.nested_regions] == ["child"]


def test_table_note_requires_strong_not_only_center_containment():
    parent = region("parent", "Table", [0, 0, 100, 100])
    note = region("note", "Footnote", [10, 70, 120, 95], text="note")
    config = ContainmentConfig(strong_child_coverage=0.95, center_child_coverage=0.70)
    proposals = analyze_nested_containment([parent, note], config=config)
    result = resolve_nested_hierarchy([parent, note], proposals, config)
    assert result.decisions[0]["reason"] == "table_note_not_strongly_contained"
    assert result.nested_regions == []


def test_shared_center_and_area_thresholds_control_candidates():
    parent = region("parent", "Table", [0, 0, 100, 100])
    child = region("child", "Text", [10, 10, 120, 90], text="cell")
    config = ContainmentConfig(
        strong_child_coverage=0.99,
        center_child_coverage=0.70,
        max_child_parent_area_ratio=0.50,
    )
    proposals = analyze_nested_containment([parent, child], config=config)
    assert len(proposals) == 1
    result = resolve_nested_hierarchy([parent, child], proposals, config)
    assert result.decisions[0]["reason"] == "child_too_large_for_parent"


def test_one_authoritative_outcome_per_pair():
    result = outcome("Table", "Text", "cell")
    pair = ("parent", "child")
    matching = [
        rel
        for rel in result.relationships
        if (rel["left_region_id"], rel["right_region_id"]) == pair
    ]
    assert len(matching) == 1


def test_observational_candidate_flows_to_one_authoritative_policy_outcome():
    regions = [
        region("parent", "Table", [0, 0, 500, 500], text=""),
        region("child", "Text", [10, 10, 100, 60], text="cell"),
    ]
    observations = resolve_layout_overlaps(
        regions,
        [{"page_number": 1, "image_width_px": 1000, "image_height_px": 1000}],
        containment=ContainmentConfig(),
    )
    candidate = [
        relation
        for relation in observations.relationships
        if relation["kind"] == "CONTAINMENT_CANDIDATE"
    ]
    assert len(candidate) == 1
    assert all(r["emission_policy"] == "emit_canonical" for r in observations.regions)
    proposals = analyze_nested_containment(
        observations.regions, observations.relationships, config=ContainmentConfig()
    )
    resolved = resolve_nested_hierarchy(
        observations.regions, proposals, ContainmentConfig()
    )
    assert len(resolved.relationships) == 1
    assert resolved.relationships[0]["kind"] == "NESTED_CHILD"


def test_figure_internal_semantic_hint_overrides_length_only_paragraph_guess():
    result = outcome(
        "Figure", "Text", "long legend entry " * 12, semantic_role="legend"
    )
    assert result.decisions[0]["kind"] == "NESTED_CHILD"
    assert result.decisions[0]["inferred_child_role"] == "figure_internal_text"


def test_plot_title_and_legend_list_are_supported_figure_children():
    assert outcome(
        "Figure", "Title", "Observed and modelled", semantic_role="plot_title"
    ).decisions[0]["kind"] == "NESTED_CHILD"
    assert outcome(
        "Figure", "List", "N0\nN1\nN2", semantic_role="legend"
    ).decisions[0]["kind"] == "NESTED_CHILD"
    assert outcome("Figure", "Title", "Methods").decisions[0]["kind"] == (
        "INVALID_OCCLUSION"
    )


def test_caption_protection_keeps_external_semantic_sibling_top_level():
    parent = region("figure", "Figure", [0, 0, 500, 500])
    caption = region("caption", "Caption", [20, 470, 480, 530], text="Figure 1. Test")
    proposals = analyze_nested_containment([parent, caption])
    result = resolve_nested_hierarchy(
        [parent, caption], proposals, protected_child_ids={"caption"}
    )
    assert result.nested_regions == []
    assert {row["layout_region_id"] for row in result.top_level_regions} == {
        "figure",
        "caption",
    }
