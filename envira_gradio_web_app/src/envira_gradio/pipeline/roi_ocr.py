"""Cached, observable OCR for small source-PDF regions.

The layout core owns the decision to request OCR. This module owns rendering,
coordinate mapping, resource cleanup, caching, and failure circuit breaking so
one missing OCR dependency is not retried for every page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class RoiOcrError(RuntimeError):
    """An OCR request failed with page/ROI context preserved."""

    def __init__(self, message: str, *, category: str, retryable: bool) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable


def _failure_category(exc: Exception) -> tuple[str, bool]:
    """Separate environment failures from page-local data failures."""
    message = f"{type(exc).__name__}: {exc}".casefold()
    dependency_markers = (
        "tesseract",
        "ocr language",
        "language data",
        "traineddata",
        "not installed",
        "not found",
    )
    if any(marker in message for marker in dependency_markers):
        return "dependency_unavailable", False
    if isinstance(exc, (MemoryError, ImportError, ModuleNotFoundError)):
        return "runtime_unavailable", False
    return "page_ocr_failure", True


@dataclass
class RoiOcrSession:
    dpi: int = 300
    language: str = "eng"
    cache_enabled: bool = True
    disable_after_failure: bool = True
    _cache: dict[tuple[Any, ...], list[tuple[Any, ...]]] = field(default_factory=dict)
    _disabled_error: str | None = None
    attempts: int = 0
    cache_hits: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)
    skipped_by_circuit: int = 0
    empty_results: int = 0

    def words(self, page: Any, roi: Any, fitz_module: Any) -> list[tuple[Any, ...]]:
        """OCR an ROI once and return words mapped to source-PDF coordinates."""
        page_number = int(getattr(page, "number", -1)) + 1
        coordinates = tuple(float(value) for value in (roi.x0, roi.y0, roi.x1, roi.y1))
        if not all(
            value == value and abs(value) != float("inf") for value in coordinates
        ):
            raise ValueError(f"ROI coordinates must be finite: {coordinates}")
        if coordinates[2] <= coordinates[0] or coordinates[3] <= coordinates[1]:
            raise ValueError(f"ROI must have positive area: {coordinates}")
        key = (
            page_number,
            *(round(value, 3) for value in coordinates),
            self.dpi,
            self.language,
        )
        if self.cache_enabled and key in self._cache:
            self.cache_hits += 1
            return list(self._cache[key])
        if self._disabled_error is not None:
            self.skipped_by_circuit += 1
            raise RoiOcrError(
                f"OCR circuit open after prior failure: {self._disabled_error}",
                category="circuit_open",
                retryable=False,
            )

        self.attempts += 1
        ocr_doc = None
        try:
            zoom = float(self.dpi) / 72.0
            pix = page.get_pixmap(
                matrix=fitz_module.Matrix(zoom, zoom), clip=roi, alpha=False
            )
            ocr_bytes = pix.pdfocr_tobytes(language=self.language)
            ocr_doc = fitz_module.open(stream=ocr_bytes, filetype="pdf")
            ocr_page = ocr_doc.load_page(0)
            ocr_rect = ocr_page.rect
            sx = roi.width / max(float(ocr_rect.width), 1e-9)
            sy = roi.height / max(float(ocr_rect.height), 1e-9)
            mapped = []
            for raw_word in ocr_page.get_text("words", sort=True):
                if len(raw_word) < 8:
                    continue
                x0, y0, x1, y1, text, block_no, line_no, word_no = raw_word[:8]
                mapped.append(
                    (
                        float(roi.x0) + float(x0) * sx,
                        float(roi.y0) + float(y0) * sy,
                        float(roi.x0) + float(x1) * sx,
                        float(roi.y0) + float(y1) * sy,
                        text,
                        block_no,
                        line_no,
                        word_no,
                    )
                )
            if self.cache_enabled:
                self._cache[key] = list(mapped)
            if not mapped:
                self.empty_results += 1
            return mapped
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            category, retryable = _failure_category(exc)
            self.failures.append(
                {
                    "page_number": page_number,
                    "roi_bbox_pt": list(key[1:5]),
                    "error": message,
                    "category": category,
                    "retryable": retryable,
                }
            )
            if self.disable_after_failure and not retryable:
                self._disabled_error = message
            raise RoiOcrError(
                f"ROI OCR failed on page {page_number} for {list(key[1:5])}: {message}",
                category=category,
                retryable=retryable,
            ) from exc
        finally:
            if ocr_doc is not None:
                ocr_doc.close()

    def diagnostics(self) -> dict[str, Any]:
        return {
            "attempts": self.attempts,
            "cache_hits": self.cache_hits,
            "cached_roi_count": len(self._cache),
            "circuit_open": self._disabled_error is not None,
            "skipped_by_circuit": self.skipped_by_circuit,
            "empty_results": self.empty_results,
            "failures": list(self.failures),
            "dpi": self.dpi,
            "language": self.language,
        }
