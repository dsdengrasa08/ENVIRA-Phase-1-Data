from types import SimpleNamespace

import fitz

from envira_pdf_layout.pdf_io import PageSource, prepare_pages


def _document(tmp_path):
    source_path = tmp_path / "source.pdf"
    source = fitz.open()
    source.new_page(width=144, height=216).insert_text((20, 30), "ENVIRA")
    source.save(source_path)
    source.close()
    page_pdf_dir = tmp_path / "page_pdfs"
    page_image_dir = tmp_path / "page_images"
    page_pdf_dir.mkdir()
    page_image_dir.mkdir()
    return SimpleNamespace(
        pdf_path=source_path,
        page_start=1,
        page_end=1,
        artifacts=SimpleNamespace(
            page_pdf_dir=page_pdf_dir,
            page_image_dir=page_image_dir,
            page_records_jsonl=tmp_path / "page_records.jsonl",
        ),
    )


def test_prepare_pages_uses_one_source_and_skips_page_pdfs_by_default(tmp_path):
    document = _document(tmp_path)
    metrics = {}

    page_set = prepare_pages(document, 180, metrics=metrics)

    page = page_set.pages[0]
    assert page.width_px == 360
    assert page.height_px == 540
    assert page.page_image_path.is_file()
    assert not page.page_pdf_path.exists()
    assert metrics == {
        "pdf_opens": 1,
        "pages_rendered": 1,
        "page_pdfs_materialized": 0,
    }


def test_prepare_pages_can_materialize_compatibility_page_pdf(tmp_path):
    document = _document(tmp_path)
    metrics = {}

    page_set = prepare_pages(
        document, 180, materialize_page_pdfs=True, metrics=metrics
    )

    page = page_set.pages[0]
    assert page.page_pdf_path.is_file()
    with fitz.open(page.page_pdf_path) as generated:
        assert generated.page_count == 1
        assert "ENVIRA" in generated[0].get_text()
    assert metrics["page_pdfs_materialized"] == 1


def test_page_source_reuses_open_document_for_text_extraction(tmp_path):
    document = _document(tmp_path)

    with PageSource(document.pdf_path) as source:
        first = source.extract_words(1)
        second = source.extract_words(1)

    assert first == second
    assert first[0][4] == "ENVIRA"
    assert source.counters["pdf_opens"] == 1
