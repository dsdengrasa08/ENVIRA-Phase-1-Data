from copy import deepcopy

from envira_pdf_layout.config import OverlapResolutionConfig
from envira_pdf_layout.layout_overlap import (
    associate_attachable_context,
    overlap_features,
    resolve_layout_overlaps,
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
        "reading_order_column": "single",
        "score": score,
    }


def test_directional_features_include_centers_axes_gaps_and_alignment():
    features = overlap_features(
        region("small", "Text", [100, 100, 200, 130]),
        region("large", "Figure", [90, 90, 700, 500]),
        PAGES[0],
    )
    assert features["a_containment"] == 1
    assert features["a_center_inside_b"] is True
    assert features["b_center_inside_a"] is False
    assert features["a_horizontal_coverage"] == 1
    assert features["horizontal_gap_page_ratio"] == 0


def test_source_geometry_is_immutable_and_auditable():
    raw = [
        region("a", "Text", [100, 100, 400, 150], "same", score=None),
        region("b", "Text", [101, 100, 399, 151], "same", score=0.8),
    ]
    before = deepcopy(raw)
    result = resolve_layout_overlaps(raw, PAGES)
    assert raw == before
    assert len(result.regions) == 1
    assert result.regions[0]["source_bbox_px"] == [101, 100, 399, 151]
    assert result.regions[0]["resolved_bbox_px"] == [101, 100, 399, 151]
    assert result.regions[0]["source_region_ids"] == ["b", "a"]
    assert result.decisions[0]["confidence"] == "high"


def test_cross_class_near_identical_regions_are_flagged_not_deleted():
    result = resolve_layout_overlaps(
        [
            region("heading", "Section-header", [100, 100, 500, 150], "Methods"),
            region("paragraph", "Text", [101, 100, 499, 151], "Different"),
        ],
        PAGES,
    )
    assert len(result.regions) == 2
    assert result.suppressed == []
    assert result.relationships[0]["kind"] == "CLASS_CONFLICT"
    assert result.relationships[0]["status"] == "unresolved_conflict"
    assert all(r["resolution_status"] == "ambiguous" for r in result.regions)


def test_asset_containment_is_observational_and_does_not_mutate_emission():
    result = resolve_layout_overlaps(
        [
            region("figure", "Figure", [100, 100, 800, 700], order=1),
            region("label", "Text", [120, 120, 180, 150], "A", order=2),
        ],
        PAGES,
    )
    by_id = {r["layout_region_id"]: r for r in result.regions}
    assert result.relationships[0]["kind"] == "CONTAINMENT_CANDIDATE"
    assert result.relationships[0]["candidate_parent_region_id"] == "figure"
    assert result.relationships[0]["candidate_child_region_id"] == "label"
    assert by_id["label"]["emission_policy"] == "emit_canonical"
    assert "nested_parent_region_ids" not in by_id["label"]


def test_small_one_edge_protrusion_is_observed_as_near_containment():
    result = resolve_layout_overlaps(
        [
            region("figure", "Figure", [100, 100, 800, 700]),
            region("label", "Text", [775, 200, 804, 240], "axis"),
        ],
        PAGES,
    )
    relation = result.relationships[0]
    assert relation["kind"] == "CONTAINMENT_CANDIDATE"
    assert relation["features"]["b_containment"] < 0.92
    assert relation["features"]["b_protrusion_page_ratio"] == 0.004


def test_materially_protruding_text_is_not_treated_as_contained():
    result = resolve_layout_overlaps(
        [
            region("figure", "Figure", [100, 100, 800, 700]),
            region("text", "Text", [700, 200, 900, 240], "outside prose"),
        ],
        PAGES,
    )
    assert result.relationships[0]["kind"] == "CLASS_CONFLICT"


def test_non_container_containment_remains_observational_for_hierarchy_policy():
    result = resolve_layout_overlaps(
        [
            region("oversized", "Text", [50, 50, 900, 900], "bad"),
            region("title", "Title", [100, 100, 500, 160], "Title"),
            region("body", "Text", [100, 200, 500, 400], "Body"),
        ],
        PAGES,
    )
    assert {r["kind"] for r in result.relationships} == {"CONTAINMENT_CANDIDATE"}
    assert len(result.regions) == 3
    assert all(r["emission_policy"] == "emit_canonical" for r in result.regions)


def test_nearby_aligned_text_is_fragment_candidate_without_physical_merge():
    result = resolve_layout_overlaps(
        [
            region("line1", "Caption", [100, 100, 700, 130], "Figure 1. First"),
            region("line2", "Text", [100, 135, 700, 165], "continued caption"),
        ],
        PAGES,
    )
    assert result.relationships[0]["kind"] == "FRAGMENT_CANDIDATE"
    assert len(result.regions) == 2
    assert all(r["bbox_px"] == r["source_bbox_px"] for r in result.regions)


def test_duplicate_chain_requires_complete_link_consistency():
    config = OverlapResolutionConfig(
        duplicate_iou=0.80,
        duplicate_area_ratio=0.8,
        duplicate_edge_page_ratio=0.03,
    )
    result = resolve_layout_overlaps(
        [
            region("a", "Text", [100, 100, 300, 200], "same"),
            region("b", "Text", [120, 100, 320, 200], "same"),
            region("c", "Text", [140, 100, 340, 200], "same"),
        ],
        PAGES,
        config,
    )
    assert len(result.regions) == 3
    duplicate_relations = [r for r in result.relationships if r["kind"] == "DUPLICATE"]
    assert len(duplicate_relations) == 2
    assert all(
        r["status"] == "retained_nontransitive_duplicate_chain"
        for r in duplicate_relations
    )


def test_caption_association_supports_figures_and_preserves_ambiguity():
    associated = associate_attachable_context(
        [
            region("figure", "Figure", [100, 200, 450, 500]),
            region("caption", "Caption", [100, 505, 450, 550], "Figure 1. Result"),
        ],
        PAGES,
    )
    assert associated[0]["kind"] == "CAPTION_OF"
    assert associated[0]["parent_region_id"] == "figure"
    ambiguous = associate_attachable_context(
        [
            region("left", "Figure", [50, 200, 450, 500]),
            region("right", "Figure", [550, 200, 950, 500]),
            region("caption", "Caption", [50, 505, 950, 550], "Figure 1. Result"),
        ],
        PAGES,
    )
    assert ambiguous[0]["status"] == "unresolved_conflict"
    assert ambiguous[0]["parent_region_id"] is None


def test_explicit_caption_identifier_constrains_parent_class():
    relationships = associate_attachable_context(
        [
            region("figure", "Figure", [100, 200, 450, 500]),
            region("table", "Table", [100, 510, 450, 700]),
            region("caption", "Caption", [100, 705, 450, 750], "Table 2. Results"),
        ],
        PAGES,
    )
    assert relationships[0]["parent_region_id"] == "table"
    assert relationships[0]["caption_reference"]["kind"] == "table"
    assert {item["parent_type"] for item in relationships[0]["candidate_parents"]} == {
        "Table"
    }


def test_caption_with_no_compatible_parent_is_auditable():
    relationships = associate_attachable_context(
        [region("caption", "Caption", [100, 100, 400, 140], "Figure 9. Missing")],
        PAGES,
    )
    assert relationships[0]["status"] == "no_compatible_parent"
    assert relationships[0]["parent_region_id"] is None


def test_structural_blocker_prevents_caption_assignment():
    relationships = associate_attachable_context(
        [
            region("figure", "Figure", [100, 100, 500, 300]),
            region("heading", "Section-header", [100, 310, 500, 340], "Results"),
            region("caption", "Caption", [100, 350, 500, 390], "Figure 1. Result"),
        ],
        PAGES,
    )
    assert relationships[0]["status"] == "no_compatible_parent"


def test_disabled_resolution_still_preserves_source_and_resolved_boxes():
    result = resolve_layout_overlaps(
        [region("a", "Unknown", [1, 2, 3, 4])],
        PAGES,
        OverlapResolutionConfig(enabled=False),
    )
    assert result.relationships == []
    assert result.regions[0]["source_bbox_px"] == [1, 2, 3, 4]
    assert result.diagnostics == {"candidate_pairs": 0, "pairs_scored": 0}


def test_resolution_reports_deterministic_work_counters():
    result = resolve_layout_overlaps(
        [
            region("a", "Text", [0, 0, 100, 50], "one"),
            region("b", "Text", [0, 40, 100, 90], "two"),
        ],
        PAGES,
    )
    assert result.diagnostics["candidate_pairs"] == 1
    assert result.diagnostics["pairs_scored"] == 1
    assert result.diagnostics["relationships_emitted"] == 1


def test_sweep_line_prunes_separated_regions_before_feature_scoring():
    regions = [
        region(f"r{i}", "Text", [0, i * 100, 50, i * 100 + 10], str(i))
        for i in range(20)
    ]
    result = resolve_layout_overlaps(
        regions,
        [{"page_number": 1, "image_width_px": 100, "image_height_px": 2000}],
    )
    assert result.diagnostics["pairs_scored"] < len(regions)


def test_formula_text_boundary_penetration_trims_text_not_formula():
    result = resolve_layout_overlaps(
        [
            region("text", "Text", [100, 100, 700, 260], "prose above"),
            region("formula", "Formula", [180, 210, 620, 290], "x = y"),
        ],
        PAGES,
    )
    by_id = {r["layout_region_id"]: r for r in result.regions}
    assert by_id["text"]["bbox_px"][3] < by_id["formula"]["bbox_px"][1]
    assert by_id["formula"]["bbox_px"] == [180, 210, 620, 290]
    assert by_id["text"]["source_bbox_px"] == [100, 100, 700, 260]
    assert result.relationships[0]["kind"] == "FORMULA_TEXT_BOUNDARY_RESOLVED"
    assert result.relationships[0]["observed_kind"] == "CLASS_CONFLICT"
    assert result.decisions[-1]["action"] == "trim_text_bottom"


def test_formula_contained_in_line_addressable_text_splits_provenance_safely():
    result = resolve_layout_overlaps(
        [
            region("text", "Text", [100, 100, 700, 500], "above line\nbelow line"),
            region("formula", "Formula", [180, 240, 620, 340], "x = y"),
        ],
        PAGES,
    )
    text_regions = [r for r in result.regions if r["type"] == "Text"]
    assert len(text_regions) == 2
    assert [r["text"] for r in sorted(text_regions, key=lambda r: r["bbox_px"][1])] == [
        "above line",
        "below line",
    ]
    assert all("text" in r["source_region_ids"] for r in text_regions)
    assert all(r["source_bbox_px"] == [100, 100, 700, 500] for r in text_regions)
    assert result.decisions[-1]["action"] == "split_text_around_semantic_region"


def test_contained_formula_with_unaddressable_prose_defers_without_duplication():
    original = region("text", "Text", [100, 100, 700, 500], "one unsplittable paragraph")
    result = resolve_layout_overlaps(
        [original, region("formula", "Formula", [180, 240, 620, 340], "x = y")],
        PAGES,
    )
    assert len(result.regions) == 2
    assert next(r for r in result.regions if r["type"] == "Text")["bbox_px"] == original["bbox_px"]
    assert result.decisions[-1]["action"] == "defer_ambiguous"
    assert result.decisions[-1]["reason"] == "text_payload_not_line_addressable"


def test_inline_formula_is_retained_without_geometry_changes():
    inputs = [
        region("text", "Text", [100, 100, 800, 135], "value x equals y in prose"),
        region("formula", "Formula", [300, 105, 390, 130], "x=y"),
    ]
    result = resolve_layout_overlaps(inputs, PAGES)
    assert [r["bbox_px"] for r in result.regions] == [r["bbox_px"] for r in inputs]
    assert result.decisions[-1]["action"] == "keep_both"


def test_multiple_formula_intervals_defer_as_one_order_independent_conflict_set():
    inputs = [
        region("text", "Text", [100, 100, 700, 600], "top\nmiddle\nbottom"),
        region("f1", "Formula", [180, 220, 620, 280], "x=y"),
        region("f2", "Equation", [180, 400, 620, 460], "a=b"),
    ]
    result = resolve_layout_overlaps(inputs, PAGES)
    assert len(result.regions) == 3
    assert next(r for r in result.regions if r["type"] == "Text")["bbox_px"] == inputs[0]["bbox_px"]
    assert {d["reason"] for d in result.decisions} == {
        "multiple_formula_intervals_require_joint_resolution"
    }


def test_near_identical_formula_text_disagreement_uses_scores_when_available():
    result = resolve_layout_overlaps(
        [
            region("text", "Text", [100, 100, 600, 200], "x = y", score=0.40),
            region("formula", "Formula", [101, 100, 599, 201], "x = y", score=0.95),
        ],
        PAGES,
    )
    assert [r["layout_region_id"] for r in result.regions] == ["formula"]
    assert [r["layout_region_id"] for r in result.suppressed] == ["text"]
    assert result.relationships[0]["kind"] == "CROSS_CLASS_DETECTION_SUPPRESSED"
    assert result.decisions[-1]["action"] == "suppress_lower_confidence_detection"


def test_oversized_formula_is_trimmed_between_correct_neighboring_text_boxes():
    inputs = [
        region("above", "Text", [100, 100, 700, 210], "prose above", order=1),
        region("formula", "Formula", [100, 195, 700, 315], "x = y", order=2),
        region("below", "Text", [100, 300, 700, 400], "prose below", order=3),
    ]
    result = resolve_layout_overlaps(inputs, PAGES)
    by_id = {item["layout_region_id"]: item for item in result.regions}

    assert by_id["above"]["bbox_px"] == inputs[0]["bbox_px"]
    assert by_id["below"]["bbox_px"] == inputs[2]["bbox_px"]
    assert by_id["formula"]["source_bbox_px"] == inputs[1]["bbox_px"]
    assert by_id["formula"]["bbox_px"] == [100.0, 211.0, 700.0, 299.0]
    assert by_id["formula"]["resolution_action"] == "trim_oversized_formula_boundary"
    assert {relation["kind"] for relation in result.relationships} == {
        "FORMULA_BOUNDARY_RESOLVED"
    }
    assert {decision["adjusted_edge"] for decision in result.decisions} == {
        "top",
        "bottom",
    }


def test_formula_boundary_trim_rejects_text_containing_formula_center():
    inputs = [
        region("text", "Text", [100, 100, 800, 300], "prose containing inline math"),
        region("formula", "Formula", [300, 180, 500, 220], "x=y"),
    ]
    result = resolve_layout_overlaps(inputs, PAGES)

    assert [item["bbox_px"] for item in result.regions] == [
        item["bbox_px"] for item in inputs
    ]
    assert all(
        decision["action"] != "trim_formula_boundary"
        for decision in result.decisions
    )
