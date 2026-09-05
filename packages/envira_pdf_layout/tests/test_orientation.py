from envira_pdf_layout.orientation import (
    compatible_orientation,
    local_relation,
    normalize_angle,
    reliable_orientation_conflict,
    region_orientation,
)


def test_angles_are_normalized_without_right_angle_special_cases():
    assert normalize_angle(-90) == 270
    assert normalize_angle(372.5) == 12.5


def test_slightly_skewed_parallel_text_is_compatible():
    left = {"orientation": {"angle_degrees": 87, "confidence": 0.9, "source": "ocr"}}
    right = {"orientation": {"angle_degrees": 92, "confidence": 0.9, "source": "pdf"}}
    assert compatible_orientation(left, right) is True


def test_reverse_baseline_directions_are_axis_compatible():
    left = {"orientation_degrees": 90}
    right = {"orientation_degrees": 270}
    assert compatible_orientation(left, right) is True


def test_bbox_inference_does_not_claim_clockwise_direction():
    value = region_orientation({"type": "Caption", "bbox_px": [0, 0, 20, 200]})
    assert value == {"angle_degrees": 90.0, "confidence": 0.45, "source": "bbox_axis"}


def test_local_relation_rotates_page_side_into_logical_block_side():
    relation = local_relation([0, 0, 20, 200], [25, 0, 225, 200], 90)
    assert relation["side"] == "after"
    assert relation["overlap"] == 1.0


def test_bbox_axis_mismatch_is_not_a_reliable_orientation_conflict():
    compact_glyph = {"type": "Text", "bbox_px": [0, 0, 50, 15]}
    vertical_caption = {
        "type": "Caption",
        "bbox_px": [0, 0, 20, 200],
        "orientation": {
            "angle_degrees": 90,
            "confidence": 1.0,
            "source": "docling_provenance",
        },
    }
    assert compatible_orientation(compact_glyph, vertical_caption) is False
    assert reliable_orientation_conflict(compact_glyph, vertical_caption) is False


def test_explicit_perpendicular_directions_are_a_reliable_conflict():
    horizontal = {"orientation_degrees": 0}
    vertical = {"orientation_degrees": 90}
    assert reliable_orientation_conflict(horizontal, vertical) is True
