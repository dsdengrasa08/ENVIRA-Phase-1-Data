from envira_pdf_layout.geometry import bbox_area, clip_bbox, coverage, intersection_area


def test_bbox_primitives():
    assert clip_bbox((-1, -2, 12, 14), 10, 10) == (0.0, 0.0, 10, 10)
    assert bbox_area((0, 0, 4, 5)) == 20
    assert intersection_area((0, 0, 4, 4), (2, 2, 6, 6)) == 4
    assert coverage((1, 1, 2, 2), (0, 0, 3, 3)) == 1
