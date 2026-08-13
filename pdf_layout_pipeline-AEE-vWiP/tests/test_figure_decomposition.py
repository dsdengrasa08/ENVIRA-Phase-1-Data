from pathlib import Path

from PIL import Image, ImageDraw

from envira_pdf_layout.config import FigureFilterConfig
from envira_pdf_layout.figure_decomposition import decompose_oversized_figures


def region(region_id, typ, bbox, text=""):
    return {
        "layout_region_id": region_id,
        "page_number": 1,
        "type": typ,
        "bbox_px": list(bbox),
        "text": text,
        "width_px": bbox[2] - bbox[0],
        "height_px": bbox[3] - bbox[1],
        "area_px": (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]),
    }


def page(tmp_path: Path, rectangles):
    image = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(image)
    for box in rectangles:
        x0, y0, x1, y1 = box
        draw.rectangle((x0, y0, x1, y1), fill=(20, 20, 20))
    path = tmp_path / "page.png"
    image.save(path)
    return [
        {
            "page_number": 1,
            "image_width_px": 800,
            "image_height_px": 600,
            "page_image_path": str(path),
            "render_dpi": 180,
        }
    ]


def test_two_side_by_side_figures_with_distinct_captions_are_split(tmp_path):
    regions = [
        region("parent", "Figure", [50, 50, 750, 350]),
        region("ca", "Caption", [60, 370, 340, 410], "Figure 8. Left result"),
        region("cb", "Caption", [460, 370, 740, 410], "Fig. 9. Right result"),
    ]
    result = decompose_oversized_figures(
        regions,
        page(tmp_path, [(70, 70, 330, 330), (470, 70, 730, 330)]),
        FigureFilterConfig(),
    )
    figures = [r for r in result.regions if r["type"] == "Figure"]
    assert len(figures) == 2
    assert result.proposals[0]["decision"] == "accepted"
    assert {r["decomposition_caption_region_id"] for r in figures} == {"ca", "cb"}
    assert result.replaced_regions[0]["layout_region_id"] == "parent"


def test_unattached_provisional_caption_can_still_anchor_decomposition(tmp_path):
    regions = [
        region("parent", "Figure", [50, 50, 750, 350]),
        region("ca", "Caption", [60, 370, 340, 410], "Figure 8. Left result"),
        region("cb", "Caption", [460, 370, 740, 410], "Fig. 9. Right result"),
    ]
    provisional = [
        {
            "child_region_id": "ca",
            "parent_region_id": None,
            "status": "no_compatible_parent",
        },
        {"child_region_id": "cb", "parent_region_id": "parent", "status": "associated"},
    ]
    result = decompose_oversized_figures(
        regions,
        page(tmp_path, [(70, 70, 330, 330), (470, 70, 730, 330)]),
        FigureFilterConfig(),
        provisional,
    )
    assert result.proposals[0]["decision"] == "accepted"
    assert len([r for r in result.regions if r["type"] == "Figure"]) == 2


def test_multiple_large_panels_for_one_caption_do_not_displace_other_figure(tmp_path):
    regions = [
        region("parent", "Figure", [30, 30, 770, 400]),
        region("ca", "Caption", [40, 420, 330, 460], "Figure 8. Left result"),
        region("cb", "Caption", [430, 420, 760, 460], "Figure 9. Right result"),
    ]
    boxes = [(50, 70, 300, 350), (450, 50, 740, 180), (450, 230, 740, 370)]
    result = decompose_oversized_figures(
        regions, page(tmp_path, boxes), FigureFilterConfig()
    )
    figures = [r for r in result.regions if r["type"] == "Figure"]
    assert len(figures) == 2
    assert max(r["bbox_px"][2] - r["bbox_px"][0] for r in figures) < 400


def test_caption_pixels_inside_parent_do_not_union_with_derived_figure(tmp_path):
    regions = [
        region("parent", "Figure", [30, 30, 770, 450]),
        region("ca", "Caption", [40, 390, 330, 430], "Figure 8. Left result"),
        region("cb", "Caption", [430, 390, 760, 430], "Figure 9. Right result"),
    ]
    # Caption-like foreground is intentionally inside the oversized source box.
    boxes = [
        (50, 50, 310, 360),
        (450, 50, 740, 360),
        (45, 398, 325, 422),
        (435, 398, 755, 422),
    ]
    result = decompose_oversized_figures(
        regions, page(tmp_path, boxes), FigureFilterConfig()
    )
    figures = {
        r["decomposition_caption_region_id"]: r
        for r in result.regions
        if r["type"] == "Figure"
    }
    assert result.proposals[0]["decision"] == "accepted"
    assert figures["ca"]["bbox_px"][3] <= regions[1]["bbox_px"][1]
    assert figures["cb"]["bbox_px"][3] <= regions[2]["bbox_px"][1]


def test_caption_bbox_clips_padding_even_when_caption_pixels_are_white(tmp_path):
    regions = [
        region("parent", "Figure", [30, 30, 770, 410]),
        region("ca", "Caption", [40, 365, 330, 405], "Figure 8. Left result"),
        region("cb", "Caption", [430, 365, 760, 405], "Figure 9. Right result"),
    ]
    result = decompose_oversized_figures(
        regions,
        page(tmp_path, [(50, 50, 310, 364), (450, 50, 740, 364)]),
        FigureFilterConfig(decomposition_padding_page_ratio=0.01),
    )
    figures = [r for r in result.regions if r["type"] == "Figure"]
    assert len(figures) == 2
    assert all(r["bbox_px"][3] <= 365 for r in figures)


def test_three_figures_are_not_capped_at_two(tmp_path):
    regions = [region("parent", "Figure", [20, 30, 780, 330])]
    boxes = [(30, 50, 220, 300), (305, 50, 495, 300), (580, 50, 770, 300)]
    for i, box in enumerate(boxes, 1):
        regions.append(
            region(
                f"c{i}", "Caption", [box[0], 350, box[2], 390], f"Figure {i}. Result"
            )
        )
    result = decompose_oversized_figures(
        regions, page(tmp_path, boxes), FigureFilterConfig()
    )
    assert len([r for r in result.regions if r["type"] == "Figure"]) == 3


def test_vertically_stacked_figures_use_visual_boundaries(tmp_path):
    regions = [
        region("parent", "Figure", [100, 20, 700, 500]),
        region("ca", "Caption", [120, 225, 680, 250], "Figure 10. Upper result"),
        region("cb", "Caption", [120, 510, 680, 540], "Figure 11. Lower result"),
    ]
    boxes = [(120, 30, 680, 210), (120, 270, 680, 490)]
    result = decompose_oversized_figures(
        regions, page(tmp_path, boxes), FigureFilterConfig()
    )
    figures = [r for r in result.regions if r["type"] == "Figure"]
    assert len(figures) == 2
    assert figures[0]["bbox_px"][3] < figures[1]["bbox_px"][1]


def test_one_caption_preserves_multipanel_figure(tmp_path):
    regions = [
        region("parent", "Figure", [50, 50, 750, 350]),
        region(
            "caption", "Caption", [60, 370, 740, 410], "Figure 5. Panels (a) and (b)"
        ),
    ]
    result = decompose_oversized_figures(
        regions,
        page(tmp_path, [(70, 70, 330, 330), (470, 70, 730, 330)]),
        FigureFilterConfig(),
    )
    assert result.proposals == []
    assert result.regions[0]["layout_region_id"] == "parent"


def test_duplicate_caption_identity_does_not_trigger_split(tmp_path):
    regions = [
        region("parent", "Figure", [50, 50, 750, 350]),
        region("fragment1", "Caption", [60, 370, 300, 390], "Fig. 5. Panels"),
        region(
            "fragment2", "Caption", [300, 370, 740, 410], "Figure 5. Panels (a) and (b)"
        ),
    ]
    result = decompose_oversized_figures(
        regions,
        page(tmp_path, [(70, 70, 330, 330), (470, 70, 730, 330)]),
        FigureFilterConfig(),
    )
    assert result.proposals == []


def test_multiple_captions_without_visual_separation_preserve_original(tmp_path):
    regions = [
        region("parent", "Figure", [50, 50, 750, 350]),
        region("ca", "Caption", [60, 370, 340, 410], "Figure 2. First"),
        region("cb", "Caption", [460, 370, 740, 410], "Figure 3. Second"),
    ]
    result = decompose_oversized_figures(
        regions, page(tmp_path, [(60, 60, 740, 340)]), FigureFilterConfig()
    )
    assert [r["layout_region_id"] for r in result.regions if r["type"] == "Figure"] == [
        "parent"
    ]
    assert result.proposals[0]["decision"] == "preserve_ambiguous"


def test_missing_page_image_is_a_non_destructive_ambiguity(tmp_path):
    regions = [
        region("parent", "Figure", [50, 50, 750, 350]),
        region("ca", "Caption", [60, 370, 340, 410], "Figure A. First"),
        region("cb", "Caption", [460, 370, 740, 410], "Figure B. Second"),
    ]
    pages = [
        {
            "page_number": 1,
            "image_width_px": 800,
            "image_height_px": 600,
            "page_image_path": str(tmp_path / "missing.png"),
        }
    ]
    result = decompose_oversized_figures(regions, pages, FigureFilterConfig())
    assert result.regions[0]["layout_region_id"] == "parent"
    assert result.proposals[0]["reason"] == "page_image_unavailable"
