from copy import deepcopy

from envira_pdf_layout.figure_completion import validate_figure_completions
from envira_pdf_layout.nested_containment import analyze_nested_containment


def region(region_id, typ, bbox, *, text="", page=1, **extra):
    return {
        "layout_region_id": region_id,
        "page_number": page,
        "type": typ,
        "bbox_px": bbox,
        "text": text,
        "width_px": bbox[2] - bbox[0],
        "height_px": bbox[3] - bbox[1],
        "area_px": (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]),
        **extra,
    }


def completed_figure(proposed=(100, 100, 500, 500), **extra):
    assignment_score = extra.pop("figure_completion_assignment_score", 9.0)
    return region(
        "figure",
        "Figure",
        list(proposed),
        figure_completion_original_bbox_px=[100, 300, 500, 500],
        figure_completion_candidate_bbox_px=[100, 100, 500, 300],
        figure_completion_caption_region_id="caption",
        figure_completion_assignment_score=assignment_score,
        **extra,
    )


def test_safe_proposal_is_accepted_with_immutable_geometry_history():
    figure = completed_figure()
    original = deepcopy(figure)
    result = validate_figure_completions([figure], [figure])
    assert figure == original
    resolved = result.regions[0]
    assert resolved["source_bbox_px"] == [100, 300, 500, 500]
    assert resolved["proposed_bbox_px"] == [100, 100, 500, 500]
    assert resolved["resolved_bbox_px"] == [100, 100, 500, 500]
    assert resolved["visual_crop_bbox_px"] == [100, 100, 500, 300]
    assert resolved["semantic_group_bbox_px"] == [100, 100, 500, 500]
    assert resolved["geometry_history"][1]["accepted"] is True
    assert result.proposals[0]["proposal_schema_version"] == 1
    assert result.proposals[0]["decision"] == "accepted"


def test_body_paragraph_barrier_rejects_and_restores_source_geometry():
    figure = completed_figure()
    body = region("body", "Text", [120, 150, 480, 230], text="x" * 100)
    result = validate_figure_completions([figure, body], [figure, body])
    resolved = result.regions[0]
    assert resolved["bbox_px"] == [100, 300, 500, 500]
    assert resolved["resolved_bbox_px"] == resolved["source_bbox_px"]
    assert resolved["geometry_version"] == 1
    assert result.proposals[0]["decision"] == "rejected_barrier_crossing"
    assert result.proposals[0]["barrier_region_ids"] == ("body",)


def test_heading_table_and_other_figure_are_hard_conflicts():
    for typ in ("Section-header", "Table", "Figure"):
        figure = completed_figure()
        obstacle = region("obstacle", typ, [120, 150, 480, 230])
        result = validate_figure_completions([figure, obstacle], [figure, obstacle])
        proposal = result.proposals[0]
        expected = (
            "ambiguous_competing_asset"
            if typ in {"Table", "Figure"}
            else "rejected_barrier_crossing"
        )
        assert proposal["decision"] == expected


def test_formula_and_short_panel_label_are_accepted_nested_content():
    figure = completed_figure()
    formula = region("formula", "Formula", [120, 150, 180, 190], text="x")
    label = region("label", "Text", [200, 150, 220, 175], text="A")
    result = validate_figure_completions(
        [figure, formula, label], [figure, formula, label]
    )
    assert result.proposals[0]["decision"] == "accepted_with_nested_content"
    assert set(result.proposals[0]["newly_captured_region_ids"]) == {"formula", "label"}


def test_excessive_growth_and_weak_caption_score_are_not_promoted():
    excessive = completed_figure(proposed=(0, 0, 1000, 1000))
    result = validate_figure_completions(
        [excessive], [excessive], max_area_multiplier=2.0
    )
    assert result.proposals[0]["decision"] == "rejected_excessive_growth"
    weak = completed_figure(figure_completion_assignment_score=1.0)
    result = validate_figure_completions([weak], [weak], min_assignment_score=7.0)
    assert result.proposals[0]["decision"] == "ambiguous_visual_evidence"


def test_proposals_are_deterministic_and_page_local():
    figure = completed_figure()
    other_page = region("body", "Text", [120, 150, 480, 230], text="x" * 100, page=2)
    first = validate_figure_completions([figure, other_page], [figure, other_page])
    second = validate_figure_completions([figure, other_page], [figure, other_page])
    assert first.proposals == second.proposals
    assert first.proposals[0]["newly_captured_region_ids"] == ()


def test_column_gutter_crossing_is_rejected_without_capturing_text():
    figure = completed_figure(proposed=(50, 100, 800, 500))
    figure["figure_completion_original_bbox_px"] = [50, 300, 400, 500]
    left = region("left", "Text", [20, 600, 400, 700], text="l" * 100)
    right = region("right", "Text", [600, 600, 980, 700], text="r" * 100)
    result = validate_figure_completions(
        [figure, left, right],
        [figure, left, right],
        pages=[{"page_number": 1, "image_width_px": 1000, "image_height_px": 1000}],
        max_area_multiplier=10,
    )
    assert result.proposals[0]["crosses_column_gutter"] is True
    assert result.proposals[0]["reason"] == "proposal_crosses_column_gutter"


def test_proposed_geometry_is_clipped_to_page_before_validation():
    figure = completed_figure(proposed=(-20, -30, 1100, 1200))
    result = validate_figure_completions(
        [figure],
        [figure],
        pages=[{"page_number": 1, "image_width_px": 1000, "image_height_px": 1000}],
    )
    assert result.proposals[0]["proposed_bbox_px"] == [0.0, 0.0, 1000.0, 1000.0]
    assert result.proposals[0]["decision"] == "rejected_excessive_growth"


def test_rejected_expansion_does_not_create_downstream_containment():
    figure = completed_figure()
    body = region("body", "Text", [120, 150, 480, 230], text="x" * 100)
    validation = validate_figure_completions([figure, body], [figure, body])
    proposals = analyze_nested_containment(validation.regions)
    assert not any(item["child_region_id"] == "body" for item in proposals)


def test_region_without_completion_metadata_produces_no_proposal():
    plain = region("figure", "Figure", [10, 10, 100, 100])
    result = validate_figure_completions([plain], [plain])
    assert result.proposals == []
    assert result.regions[0]["source_bbox_px"] == plain["bbox_px"]
