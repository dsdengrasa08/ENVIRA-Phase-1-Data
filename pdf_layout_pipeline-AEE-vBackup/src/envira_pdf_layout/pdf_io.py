"""PDF page extraction, rendering, and generic text-layer access."""

from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import time
from .types import DocumentIdentity, PageRecord, PageSet


def _write_bytes_resilient(path: Path, data: bytes, attempts: int = 3) -> None:
    """Write through Python rather than MuPDF's fragile direct FUSE writer.

    Colab-mounted Drive paths can abort a native ``fwrite`` even though a normal
    Python copy succeeds.  Build the file locally, then replace a same-directory
    temporary target so consumers never observe a partial page artifact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    error = None
    for attempt in range(attempts):
        local_name = None
        target_tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with tempfile.NamedTemporaryFile(delete=False) as local:
                local_name = local.name
                local.write(data)
                local.flush()
                os.fsync(local.fileno())
            with open(local_name, "rb") as source, target_tmp.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            target_tmp.replace(path)
            return
        except OSError as exc:
            error = exc
            target_tmp.unlink(missing_ok=True)
            if attempt + 1 < attempts:
                time.sleep(0.25 * (attempt + 1))
        finally:
            if local_name:
                Path(local_name).unlink(missing_ok=True)
    raise OSError(
        f"Could not write page artifact after {attempts} attempts: {path}"
    ) from error


def prepare_pages(document: DocumentIdentity, render_dpi: int = 180) -> PageSet:
    import pymupdf

    pages: list[PageRecord] = []
    scale = render_dpi / 72.0
    with pymupdf.open(document.pdf_path) as source:
        for page_number in range(document.page_start, document.page_end + 1):
            page = source[page_number - 1]
            pdf_path = document.artifacts.page_pdf_dir / f"page_{page_number:04d}.pdf"
            image_path = (
                document.artifacts.page_image_dir / f"page_{page_number:04d}.png"
            )
            with pymupdf.open() as one_page:
                one_page.insert_pdf(
                    source, from_page=page_number - 1, to_page=page_number - 1
                )
                _write_bytes_resilient(pdf_path, one_page.tobytes())
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            _write_bytes_resilient(image_path, pixmap.tobytes("png"))
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
    import pymupdf

    with pymupdf.open(pdf_path) as document:
        return document[page_number - 1].get_text("words", clip=clip)
