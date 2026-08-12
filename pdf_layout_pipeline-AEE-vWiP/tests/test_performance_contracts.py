from envira_pdf_layout.caption_association import associate_captions
from envira_pdf_layout.config import CaptionAssociationConfig, ContainmentConfig
from envira_pdf_layout.layout_overlap import resolve_layout_overlaps
from envira_pdf_layout.nested_containment import analyze_nested_containment
from envira_pdf_layout.region_index import RegionIndex
import random
import pytest

pytestmark = pytest.mark.performance


PAGES = [{"page_number": 1, "image_width_px": 1000, "image_height_px": 1000}]


def region(region_id, typ, bbox, text=""):
    return {
        "layout_region_id": region_id,
        "page_number": 1,
        "type": typ,
        "bbox_px": bbox,
        "text": text,
        "reading_order_column": "single",
    }


def test_overlap_features_are_reused_by_hierarchy_proposals():
    regions = [
        region("table", "Table", [0, 0, 500, 500]),
        region("cell", "Text", [10, 10, 100, 50], "cell"),
    ]
    overlap = resolve_layout_overlaps(regions, PAGES)
    metrics = {}
    proposals = analyze_nested_containment(
        overlap.regions,
        overlap.relationships,
        config=ContainmentConfig(),
        index=RegionIndex.build(overlap.regions, PAGES),
        metrics=metrics,
    )
    assert len(proposals) == 1
    assert metrics["pairs_scored"] == 0
    assert metrics["observations_examined"] == 1


def test_shared_index_preserves_caption_results():
    regions = [
        region("figure", "Figure", [100, 100, 400, 300]),
        region("caption", "Caption", [100, 305, 400, 340], "Figure 1. Test"),
    ]
    config = CaptionAssociationConfig()
    ordinary = associate_captions(regions, PAGES, config=config)
    indexed = associate_captions(
        regions, PAGES, config=config, index=RegionIndex.build(regions, PAGES)
    )
    assert indexed == ordinary


def test_caption_association_is_deterministic_under_input_permutations():
    regions = [
        region("left", "Figure", [50, 100, 450, 300]),
        region("right", "Figure", [550, 100, 950, 300]),
        region("caption", "Caption", [50, 305, 950, 340], "Figure 1. Test"),
    ]
    expected = associate_captions(regions, PAGES)
    rng = random.Random(11)
    for _ in range(10):
        shuffled = list(regions)
        rng.shuffle(shuffled)
        assert associate_captions(shuffled, PAGES) == expected
