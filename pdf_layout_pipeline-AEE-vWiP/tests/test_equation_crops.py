from pathlib import Path

from PIL import Image, ImageDraw

from envira_pdf_layout.config import EquationCropConfig
from envira_pdf_layout.equation_crops import refine_equation_visual_crops
from envira_pdf_layout.geometry import intersection_area


def region(region_id, typ, bbox, text="", column="single", **extra):
    return {
        "layout_region_id": region_id,
        "page_number": 1,
        "type": typ,
        "bbox_px": list(bbox),
        "resolved_bbox_px": list(bbox),
        "text": text,
        "reading_order_column": column,
        **extra,
    }


def page(tmp_path: Path | None = None, ink=(), size=(1000, 1000)):
    record = {
        "page_number": 1,
        "image_width_px": size[0],
        "image_height_px": size[1],
    }
    if tmp_path is not None:
        path = tmp_path / "page.png"
        image = Image.new("L", size, 255)
        draw = ImageDraw.Draw(image)
        for box in ink:
            draw.rectangle(box, fill=0)
        image.save(path)
        record["page_image_path"] = str(path)
    return [record]


def refined(regions, pages=None, **config):
    return refine_equation_visual_crops(
        regions, pages or page(), EquationCropConfig(**config)
    )


def test_isolated_equation_gets_scale_aware_visual_margin_only():
    source = region("eq", "Formula", [300, 300, 600, 350], "x=y")
    result = refined([source])
    equation = result.regions[0]
    assert equation["bbox_px"] == source["bbox_px"]
    assert equation["resolved_bbox_px"] == source["resolved_bbox_px"]
    assert equation["visual_crop_bbox_px"] == [282.5, 285.0, 617.5, 365.0]
    assert result.changed is True


def test_short_equation_uses_page_scale_minimum_vertical_margin():
    source = region("eq", "Formula", [300, 300, 600, 310], "x=y")
    result = refined([source])
    crop = result.regions[0]["visual_crop_bbox_px"]
    assert crop[1] == 294.0
    assert crop[3] == 316.0
    assert result.decisions[0]["desired_margin_px"]["vertical"] == 6.0


def test_text_above_and_below_independently_limit_vertical_edges():
    regions = [
        region("above", "Text", [250, 200, 650, 292], "above"),
        region("eq", "Formula", [300, 300, 600, 350], "x=y"),
        region("below", "Text", [250, 356, 650, 450], "below"),
    ]
    crop = refined(regions).regions[1]["visual_crop_bbox_px"]
    assert crop[1] == 298.0
    assert crop[3] == 350.0
    assert intersection_area(tuple(crop), tuple(regions[0]["bbox_px"])) == 0
    assert intersection_area(tuple(crop), tuple(regions[2]["bbox_px"])) == 0


def test_equation_immediately_followed_by_text_keeps_other_margins():
    regions = [
        region("eq", "Formula", [300, 300, 600, 350], "x=y"),
        region("below", "Text", [250, 351, 650, 410], "below"),
    ]
    crop = refined(regions).regions[0]["visual_crop_bbox_px"]
    assert crop[:3] == [282.5, 285.0, 617.5]
    assert crop[3] == 350.0


def test_consecutive_equations_share_gap_without_overlap_or_merge():
    regions = [
        region("a", "Formula", [300, 300, 600, 350], "a=b"),
        region("b", "Equation", [300, 360, 600, 410], "c=d"),
    ]
    result = refined(regions)
    first, second = result.regions
    assert len(result.regions) == 2
    assert first["visual_crop_bbox_px"][3] < second["visual_crop_bbox_px"][1]
    assert first["visual_crop_bbox_px"][3] == 352.0
    assert second["visual_crop_bbox_px"][1] == 358.0


def test_several_consecutive_equations_are_order_independent():
    regions = [
        region("a", "Formula", [300, 200, 600, 240]),
        region("b", "Formula", [300, 250, 600, 290]),
        region("c", "Formula", [300, 300, 600, 340]),
    ]
    forward = refined(regions).regions
    reverse = refined(list(reversed(regions))).regions
    assert {r["layout_region_id"]: r["visual_crop_bbox_px"] for r in forward} == {
        r["layout_region_id"]: r["visual_crop_bbox_px"] for r in reverse
    }


def test_other_column_is_a_structural_horizontal_boundary():
    regions = [
        region("eq", "Formula", [400, 300, 480, 350], column="left"),
        region("left-text", "Text", [50, 100, 480, 200], column="left"),
        region("right-text", "Text", [520, 100, 950, 450], column="right"),
    ]
    decision = refined(regions).decisions[0]
    crop = refined(regions).regions[0]["visual_crop_bbox_px"]
    assert crop[2] < 500
    assert decision["blockers"]["right"] in {"column", "right-text"}


def test_figure_and_table_are_hard_boundaries():
    for typ in ("Figure", "Table"):
        regions = [
            region("eq", "Formula", [300, 300, 600, 350]),
            region("asset", typ, [610, 250, 900, 500]),
        ]
        crop = refined(regions).regions[0]["visual_crop_bbox_px"]
        assert crop[2] <= 604.0
        assert intersection_area(tuple(crop), tuple(regions[1]["bbox_px"])) == 0


def test_right_aligned_equation_number_is_included_but_prose_is_not():
    regions = [
        region("eq", "Formula", [200, 300, 500, 350], "x=y"),
        region("number", "Text", [700, 305, 730, 345], "(3)"),
        region("prose", "Text", [760, 300, 950, 350], "unrelated prose"),
    ]
    result = refined(regions)
    crop = result.regions[0]["visual_crop_bbox_px"]
    assert crop[2] >= 730
    assert crop[2] <= 754
    assert result.decisions[0]["associated_equation_number_region_ids"] == ["number"]


def test_multiline_equation_uses_full_detector_union_and_keeps_physical_box():
    source = region("eq", "Equation", [200, 200, 700, 320], "a=b\nc=d")
    equation = refined([source]).regions[0]
    crop = equation["visual_crop_bbox_px"]
    assert crop[0] < 200 and crop[1] < 200 and crop[2] > 700 and crop[3] > 320
    assert equation["bbox_px"] == [200, 200, 700, 320]


def test_already_well_padded_equation_is_preserved(tmp_path):
    source = region("eq", "Formula", [200, 200, 500, 300], "x=y")
    pages = page(tmp_path, ink=[(250, 225, 450, 275)])
    result = refined([source], pages)
    assert result.regions[0]["visual_crop_bbox_px"] == source["bbox_px"]
    assert result.decisions[0]["reason"] == "sufficient_existing_visual_margin"


def test_visible_content_wall_stops_whitespace_expansion(tmp_path):
    source = region("eq", "Formula", [200, 200, 500, 300], "x=y")
    pages = page(tmp_path, ink=[(200, 200, 499, 299), (510, 200, 515, 300)])
    crop = refined([source], pages).regions[0]["visual_crop_bbox_px"]
    assert crop[2] == 510.0


def test_page_boundary_clips_each_edge():
    source = region("eq", "Formula", [0, 0, 200, 50], "x=y")
    crop = refined([source]).regions[0]["visual_crop_bbox_px"]
    assert crop[0] == 0 and crop[1] == 0
    assert crop[2] > 200 and crop[3] > 50


def test_nested_equation_crop_stays_inside_parent():
    parent = region("table", "Table", [100, 100, 500, 500])
    equation = region(
        "eq", "Formula", [105, 200, 490, 250], nested_parent_region_ids=["table"]
    )
    crop = refined([parent, equation]).regions[1]["visual_crop_bbox_px"]
    assert crop[0] >= 100 and crop[2] <= 500
