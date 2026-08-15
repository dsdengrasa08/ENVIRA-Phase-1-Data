from types import SimpleNamespace

from envira_pdf_layout.pipeline import _protected_caption_ids
from envira_pdf_layout.results import legacy_final_regions_dataframe, regions_dataframe


def _region(region_id, kind, bbox):
    return {
        "layout_region_id": region_id,
        "page_number": 1,
        "type": kind,
        "bbox_px": bbox,
    }


def test_external_associated_caption_is_protected_from_figure_ownership():
    figure = _region("figure", "Figure", [100, 100, 500, 400])
    caption = _region("caption", "Caption", [100, 390, 500, 440])
    associations = [
        {
            "child_region_id": "caption",
            "parent_region_id": "figure",
            "status": "associated",
        }
    ]

    assert _protected_caption_ids(associations, [figure, caption], 0.82) == {
        "caption"
    }


def test_internal_caption_like_identifier_is_not_protected():
    figure = _region("figure", "Figure", [100, 100, 500, 400])
    identifier = _region("identifier", "Caption", [120, 120, 180, 145])
    associations = [
        {
            "child_region_id": "identifier",
            "parent_region_id": "figure",
            "status": "associated",
        }
    ]

    assert _protected_caption_ids(associations, [figure, identifier], 0.82) == set()


def test_default_results_dataframe_is_document_level_not_legacy_physical_view():
    document = _region("figure", "Figure", [0, 0, 100, 100])
    nested = _region("axis", "Text", [10, 10, 20, 20])
    run = SimpleNamespace(
        document_regions=[document],
        final_regions=[document, nested],
    )

    assert regions_dataframe(run)["layout_region_id"].tolist() == ["figure"]
    assert legacy_final_regions_dataframe(run)["layout_region_id"].tolist() == [
        "figure",
        "axis",
    ]
