from types import SimpleNamespace

import pymupdf

from envira_pdf_layout.pdf_io import prepare_pages


def test_prepare_pages_writes_valid_pdf_and_png_without_pixmap_save(tmp_path):
    source_path = tmp_path / "source.pdf"
    with pymupdf.open() as source:
        page = source.new_page(width=200, height=300)
        page.insert_text((20, 30), "Caption rendering test")
        source.save(source_path)

    artifacts = SimpleNamespace(
        page_pdf_dir=tmp_path / "page_pdfs",
        page_image_dir=tmp_path / "page_images",
        page_records_jsonl=tmp_path / "page_records.jsonl",
    )
    document = SimpleNamespace(
        pdf_path=source_path,
        page_start=1,
        page_end=1,
        artifacts=artifacts,
    )
    page_set = prepare_pages(document, render_dpi=144)

    record = page_set.pages[0]
    assert record.page_pdf_path.read_bytes().startswith(b"%PDF")
    assert record.page_image_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with pymupdf.open(record.page_pdf_path) as rendered_pdf:
        assert rendered_pdf.page_count == 1
    assert record.width_px == 400
    assert record.height_px == 600
