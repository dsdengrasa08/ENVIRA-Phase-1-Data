"""PDF page inspection, rendering, and generic text-layer access."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from .types import DocumentIdentity, PageRecord, PageSet


class PageSource:
    """Run-scoped access to one PDF without repeatedly reopening the document."""

    def __init__(self, pdf_path: str | Path, render_dpi: int = 180):
        self.pdf_path = Path(pdf_path)
        self.render_dpi = render_dpi
        self._document: Any | None = None
        self.counters = {
            "pdf_opens": 0,
            "pages_rendered": 0,
            "page_pdfs_materialized": 0,
        }

    def __enter__(self) -> "PageSource":
        import pymupdf as fitz

        if self._document is None:
            self._document = fitz.open(self.pdf_path)
            self.counters["pdf_opens"] += 1
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._document is not None:
            self._document.close()
            self._document = None

    def page(self, page_number: int):
        if self._document is None:
            raise RuntimeError("PageSource must be used as a context manager")
        return self._document[page_number - 1]

    def render_page(self, page_number: int):
        import pymupdf as fitz

        scale = self.render_dpi / 72.0
        pixmap = self.page(page_number).get_pixmap(
            matrix=fitz.Matrix(scale, scale), alpha=False
        )
        self.counters["pages_rendered"] += 1
        return pixmap

    def extract_words(self, page_number: int, clip=None) -> list[tuple]:
        return self.page(page_number).get_text("words", clip=clip)

    def materialize_page_pdf(self, page_number: int, destination: str | Path) -> Path:
        import pymupdf as fitz

        destination = Path(destination)
        one_page = fitz.open()
        try:
            one_page.insert_pdf(
                self._document, from_page=page_number - 1, to_page=page_number - 1
            )
            one_page.save(destination)
        finally:
            one_page.close()
        self.counters["page_pdfs_materialized"] += 1
        return destination


def prepare_pages(
    document: DocumentIdentity,
    render_dpi: int = 180,
    *,
    materialize_page_pdfs: bool = False,
    metrics: dict[str, int] | None = None,
) -> PageSet:
    """Inspect pages and render required PNGs from one shared PDF handle.

    Individual page PDFs are compatibility artifacts and are now opt-in. Their
    deterministic paths remain in :class:`PageRecord` for on-demand creation.
    """
    pages: list[PageRecord] = []
    with PageSource(document.pdf_path, render_dpi) as source:
        for page_number in range(document.page_start, document.page_end + 1):
            page = source.page(page_number)
            pdf_path = document.artifacts.page_pdf_dir / f"page_{page_number:04d}.pdf"
            image_path = (
                document.artifacts.page_image_dir / f"page_{page_number:04d}.png"
            )
            if materialize_page_pdfs:
                source.materialize_page_pdf(page_number, pdf_path)
            pixmap = source.render_page(page_number)
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
        if metrics is not None:
            metrics.update(source.counters)
    with document.artifacts.page_records_jsonl.open("w", encoding="utf-8") as stream:
        for page in pages:
            stream.write(json.dumps(page.to_dict(), ensure_ascii=False) + "\n")
    return PageSet(document, pages)


def extract_words(pdf_path, page_number: int, clip=None) -> list[tuple]:
    with PageSource(pdf_path) as source:
        return source.extract_words(page_number, clip=clip)
