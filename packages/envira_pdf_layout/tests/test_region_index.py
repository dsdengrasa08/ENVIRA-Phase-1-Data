import pytest

from envira_pdf_layout.region_index import RegionIndex


def region(region_id, typ, page, text=""):
    return {
        "layout_region_id": region_id,
        "page_number": page,
        "type": typ,
        "bbox_px": [0, 0, 10, 10],
        "text": text,
    }


def test_index_builds_page_type_id_size_and_text_views_once():
    regions = [region("a", "Text", 1, "Hello, WORLD!"), region("b", "Figure", 2)]
    index = RegionIndex.build(
        regions,
        [
            {"page_number": 1, "image_width_px": 100, "image_height_px": 200},
            {"page_number": 2, "image_width_px": 300, "image_height_px": 400},
        ],
    )
    assert index.by_id["a"] is regions[0]
    assert index.by_page[2] == (regions[1],)
    assert index.types(1, "Text") == (regions[0],)
    assert index.page_sizes[2] == (300.0, 400.0)
    assert index.text_features["a"].normalized_text == "hello world"
    assert index.text_features["a"].tokens == ("hello", "world")


def test_index_maps_are_immutable():
    index = RegionIndex.build([region("a", "Text", 1)], [])
    with pytest.raises(TypeError):
        index.by_id["b"] = region("b", "Text", 1)
