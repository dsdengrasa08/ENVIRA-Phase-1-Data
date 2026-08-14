from pathlib import Path

from PIL import Image, ImageDraw

from envira_pdf_layout.boundary_refinement import refine_figure_boundaries
from envira_pdf_layout.config import FigureFilterConfig


def region(region_id, typ, bbox, text=""):
    return {
        "layout_region_id": region_id,
        "page_number": 1,
        "type": typ,
        "docling_label": typ.lower(),
        "bbox_px": list(bbox),
        "text": text,
    }


def page(tmp_path: Path, rectangles, size=(1000, 800)):
    path = tmp_path / "page.png"
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    for box in rectangles:
        draw.rectangle(box, fill=0)
    image.save(path)
    return [
        {
            "page_number": 1,
            "image_width_px": size[0],
            "image_height_px": size[1],
            "page_image_path": str(path),
        }
    ]


def config(**values):
    return FigureFilterConfig(refinement_min_component_area_ratio=0.0001, **values)


def test_side_by_side_oversized_edge_is_refined_at_visual_valley(tmp_path):
    regions = [
        region("a", "Figure", [50, 100, 620, 400]),
        region("b", "Figure", [540, 100, 900, 400]),
    ]
    result = refine_figure_boundaries(
        regions, page(tmp_path, [(70, 120, 400, 380), (540, 120, 880, 380)]), config()
    )
    by_id = {r["layout_region_id"]: r for r in result.regions}
    assert result.changed is True
    assert by_id["a"]["bbox_px"][2] < 540
    assert by_id["b"]["bbox_px"] == [540, 100, 900, 400]
    assert by_id["a"]["geometry_history"][-1]["stage"] == "figure_boundary_refinement"


def test_touching_side_by_side_boxes_are_treated_as_connected_conflict(tmp_path):
    """Regression for boxes like the supplied page: x1(A) == x0(B), so IoU is zero."""
    regions = [
        region("left", "Figure", [51, 47, 488, 345]),
        region("right", "Figure", [488, 47, 809, 760]),
    ]
    pages = page(
        tmp_path,
        [(72, 64, 401, 284), (515, 65, 799, 740)],
        size=(860, 800),
    )
    result = refine_figure_boundaries(regions, pages, FigureFilterConfig())
    by_id = {r["layout_region_id"]: r for r in result.regions}
    assert result.proposals[0]["intersection_area"] == 0
    assert result.proposals[0]["connected_neighbor"] is True
    assert result.proposals[0]["decision"] == "accepted"
    assert by_id["left"]["bbox_px"][2] < 488
    assert by_id["right"]["bbox_px"][0] >= 488


def test_neighbor_content_inside_oversized_box_does_not_become_its_core(tmp_path):
    """A narrow neighboring axis label in A must not make A's extension supported."""
    regions = [
        region("left", "Figure", [51, 47, 488, 345]),
        region("right", "Figure", [488, 47, 809, 760]),
    ]
    pages = page(
        tmp_path,
        [
            (72, 64, 401, 284),
            # Content belonging to the right Figure intrudes into the left source box.
            (480, 120, 487, 310),
            (515, 65, 799, 740),
        ],
        size=(860, 800),
    )
    result = refine_figure_boundaries(regions, pages, FigureFilterConfig())
    by_id = {r["layout_region_id"]: r for r in result.regions}
    assert result.proposals[0]["decision"] == "accepted"
    assert by_id["left"]["bbox_px"][2] < 480


def test_small_rounding_gap_can_trigger_analysis_but_large_clean_gap_does_not(tmp_path):
    regions = [
        region("left", "Figure", [50, 100, 499, 400]),
        region("right", "Figure", [500, 100, 900, 400]),
    ]
    pages = page(tmp_path, [(70, 120, 400, 380), (540, 120, 880, 380)])
    result = refine_figure_boundaries(regions, pages, config())
    assert result.proposals[0]["connected_neighbor"] is True
    assert result.changed is True


def test_vertically_stacked_oversized_edge_is_refined(tmp_path):
    regions = [
        region("a", "Figure", [100, 40, 700, 430]),
        region("b", "Figure", [100, 350, 700, 740]),
    ]
    result = refine_figure_boundaries(
        regions, page(tmp_path, [(130, 60, 670, 280), (130, 350, 670, 710)]), config()
    )
    by_id = {r["layout_region_id"]: r for r in result.regions}
    assert by_id["a"]["bbox_px"][3] < 350
    assert by_id["b"]["bbox_px"] == [100, 350, 700, 740]


def test_clean_gap_and_single_multipanel_figure_are_unchanged(tmp_path):
    clean = [
        region("a", "Figure", [50, 100, 400, 400]),
        region("b", "Figure", [540, 100, 900, 400]),
    ]
    pages = page(tmp_path, [(70, 120, 380, 380), (560, 120, 880, 380)])
    assert refine_figure_boundaries(clean, pages, config()).changed is False
    multipanel = [region("multi", "Figure", [50, 100, 900, 400])]
    result = refine_figure_boundaries(multipanel, pages, config())
    assert result.changed is False
    assert result.regions[0]["bbox_px"] == multipanel[0]["bbox_px"]


def test_small_overlap_without_whitespace_is_conservatively_preserved(tmp_path):
    regions = [
        region("a", "Figure", [50, 100, 510, 400]),
        region("b", "Figure", [500, 100, 900, 400]),
    ]
    pages = page(tmp_path, [(70, 120, 520, 380), (500, 120, 880, 380)])
    result = refine_figure_boundaries(
        regions, pages, config(refinement_min_conflict_smaller_ratio=0.0)
    )
    assert result.changed is False
    assert result.regions[0]["bbox_px"] == regions[0]["bbox_px"]


def test_wide_blank_margin_without_competitor_is_preserved(tmp_path):
    regions = [region("figure", "Figure", [50, 100, 900, 400])]
    result = refine_figure_boundaries(
        regions, page(tmp_path, [(70, 120, 400, 380)]), config()
    )
    assert result.regions[0]["bbox_px"] == [50, 100, 900, 400]


def test_three_neighbors_are_processed_without_merging_or_suppression(tmp_path):
    regions = [
        region("a", "Figure", [20, 100, 380, 400]),
        region("b", "Figure", [300, 100, 700, 400]),
        region("c", "Figure", [620, 100, 980, 400]),
    ]
    pages = page(
        tmp_path, [(30, 120, 260, 380), (340, 120, 580, 380), (660, 120, 960, 380)]
    )
    result = refine_figure_boundaries(regions, pages, config())
    assert len(result.regions) == 3
    assert {r["layout_region_id"] for r in result.regions} == {"a", "b", "c"}
    assert all(r["bbox_px"][0] < r["bbox_px"][2] for r in result.regions)


def test_substantial_text_in_candidate_removed_strip_protects_source_edge(tmp_path):
    regions = [
        region("a", "Figure", [50, 100, 620, 400]),
        region("b", "Figure", [540, 100, 900, 400]),
        region("body", "Text", [420, 140, 500, 240], "x" * 100),
    ]
    pages = page(tmp_path, [(70, 120, 400, 380), (540, 120, 880, 380)])
    result = refine_figure_boundaries(regions, pages, config())
    assert (
        next(r for r in result.regions if r["layout_region_id"] == "a")["bbox_px"]
        == regions[0]["bbox_px"]
    )


def test_figure_intruding_into_independent_table_is_refined_without_changing_table(
    tmp_path,
):
    regions = [
        region("figure", "Figure", [50, 100, 620, 400]),
        region("table", "Table", [540, 100, 900, 400]),
    ]
    pages = page(tmp_path, [(70, 120, 400, 380), (540, 120, 880, 380)])
    result = refine_figure_boundaries(regions, pages, config())
    by_id = {r["layout_region_id"]: r for r in result.regions}
    assert by_id["figure"]["bbox_px"][2] < 540
    assert by_id["table"]["bbox_px"] == [540, 100, 900, 400]


def test_figure_intruding_into_independent_body_text_is_refined(tmp_path):
    regions = [
        region("figure", "Figure", [50, 100, 620, 400]),
        region("body", "Text", [540, 100, 900, 400], "independent paragraph " * 8),
    ]
    pages = page(tmp_path, [(70, 120, 400, 380), (540, 120, 880, 380)])
    result = refine_figure_boundaries(regions, pages, config())
    by_id = {r["layout_region_id"]: r for r in result.regions}
    assert by_id["figure"]["bbox_px"][2] < 540
    assert by_id["body"]["bbox_px"] == [540, 100, 900, 400]
