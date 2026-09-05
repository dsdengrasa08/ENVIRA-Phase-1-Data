import random

from envira_pdf_layout.layout_overlap import overlap_features


PAGE = {"page_number": 1, "image_width_px": 1000, "image_height_px": 1000}


def region(region_id, bbox):
    return {
        "layout_region_id": region_id,
        "page_number": 1,
        "type": "Text",
        "bbox_px": bbox,
        "text": region_id,
    }


def test_pair_geometry_symmetry_and_bounded_ratios_with_fixed_seed():
    rng = random.Random(20260812)
    for index in range(250):
        ax, ay, bx, by = (rng.uniform(0, 900) for _ in range(4))
        a = [ax, ay, ax + rng.uniform(1, 100), ay + rng.uniform(1, 100)]
        b = [bx, by, bx + rng.uniform(1, 100), by + rng.uniform(1, 100)]
        forward = overlap_features(region(f"a{index}", a), region(f"b{index}", b), PAGE)
        reverse = overlap_features(region(f"b{index}", b), region(f"a{index}", a), PAGE)
        assert forward["intersection_area"] == reverse["intersection_area"]
        assert forward["iou"] == reverse["iou"]
        assert forward["a_containment"] == reverse["b_containment"]
        for key in ("iou", "a_containment", "b_containment", "area_ratio"):
            assert 0 <= forward[key] <= 1
