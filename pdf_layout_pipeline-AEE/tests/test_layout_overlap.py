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


def test_asset_containment_is_hierarchy_not_suppression():
    result = resolve_layout_overlaps(
        [
            region("figure", "Figure", [100, 100, 800, 700], order=1),
            region("label", "Text", [120, 120, 180, 150], "A", order=2),
        ],
        PAGES,
    )
    by_id = {r["layout_region_id"]: r for r in result.regions}
    assert by_id["label"]["nested_parent_region_ids"] == ["figure"]
    assert by_id["label"]["emission_policy"] == "emit_as_nested_child"
    assert by_id["label"]["parent_local_reading_order"] == 1
    assert by_id["label"]["resolved_reading_order"] is None
    assert by_id["figure"]["nested_child_region_ids"] == ["label"]


def test_non_container_covering_several_regions_is_invalid_occlusion():
    result = resolve_layout_overlaps(
        [
            region("oversized", "Text", [50, 50, 900, 900], "bad"),
            region("title", "Title", [100, 100, 500, 160], "Title"),
            region("body", "Text", [100, 200, 500, 400], "Body"),
        ],
        PAGES,
    )
    assert {r["kind"] for r in result.relationships} == {"INVALID_OCCLUSION"}
    assert len(result.regions) == 3
    assert next(r for r in result.regions if r["layout_region_id"] == "oversized")["resolution_status"] == "ambiguous"


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
    assert all(r["status"] == "retained_nontransitive_duplicate_chain" for r in duplicate_relations)


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


def test_disabled_resolution_still_preserves_source_and_resolved_boxes():
    result = resolve_layout_overlaps(
        [region("a", "Unknown", [1, 2, 3, 4])],
        PAGES,
        OverlapResolutionConfig(enabled=False),
    )
    assert result.relationships == []
    assert result.regions[0]["source_bbox_px"] == [1, 2, 3, 4]
