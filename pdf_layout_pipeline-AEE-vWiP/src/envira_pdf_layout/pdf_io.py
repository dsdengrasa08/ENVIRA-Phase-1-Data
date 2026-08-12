"""PDF page extraction, rendering, and generic text-layer access."""

from __future__ import annotations
import json
from .types import DocumentIdentity, PageRecord, PageSet


def prepare_pages(document: DocumentIdentity, render_dpi: int = 180) -> PageSet:
    import fitz

    pages: list[PageRecord] = []
    scale = render_dpi / 72.0
    with fitz.open(document.pdf_path) as source:
        for page_number in range(document.page_start, document.page_end + 1):
            page = source[page_number - 1]
            one_page = fitz.open()
            one_page.insert_pdf(
                source, from_page=page_number - 1, to_page=page_number - 1
            )
            pdf_path = document.artifacts.page_pdf_dir / f"page_{page_number:04d}.pdf"
            image_path = (
                document.artifacts.page_image_dir / f"page_{page_number:04d}.png"
            )
            one_page.save(pdf_path)
            one_page.close()
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            pixmap.save(image_path)
            pages.append(
                PageRecord(
                    page_number,
                    pdf_path,
                    image_path,
                    pixmap.width,
                    pixmap.height,
                    float(page.rect.width),
                    float(page.rect.height),
                )
            )
    with document.artifacts.page_records_jsonl.open("w", encoding="utf-8") as stream:
        for page in pages:
            stream.write(json.dumps(page.to_dict(), ensure_ascii=False) + "\n")
    return PageSet(document, pages)


def extract_words(pdf_path, page_number: int, clip=None) -> list[tuple]:
    import fitz

    with fitz.open(pdf_path) as document:
        return document[page_number - 1].get_text("words", clip=clip)
