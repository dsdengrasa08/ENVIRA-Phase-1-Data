from types import SimpleNamespace

import pytest

from envira_pdf_layout.roi_ocr import RoiOcrError, RoiOcrSession


class FakeDocument:
    def __init__(self, words):
        self.words = words
        self.closed = False

    def load_page(self, _index):
        return SimpleNamespace(
            rect=SimpleNamespace(width=100, height=50),
            get_text=lambda *_args, **_kwargs: self.words,
        )

    def close(self):
        self.closed = True


def fixtures(words=None, failure=None):
    document = FakeDocument(words or [(10, 5, 20, 10, "Header", 0, 0, 0)])
    calls = {"pixmap": 0}

    def pdfocr_tobytes(**_kwargs):
        if failure:
            raise failure
        return b"pdf"

    page = SimpleNamespace(
        number=1,
        get_pixmap=lambda **_kwargs: (
            calls.__setitem__("pixmap", calls["pixmap"] + 1)
            or SimpleNamespace(pdfocr_tobytes=pdfocr_tobytes)
        ),
    )
    roi = SimpleNamespace(x0=100, y0=20, x1=300, y1=120, width=200, height=100)
    fitz = SimpleNamespace(
        Matrix=lambda *_args: object(), open=lambda **_kwargs: document
    )
    return page, roi, fitz, document, calls


def test_maps_words_closes_document_and_reuses_cached_result():
    page, roi, fitz, document, calls = fixtures()
    session = RoiOcrSession()
    first = session.words(page, roi, fitz)
    second = session.words(page, roi, fitz)
    assert first == second == [(120.0, 30.0, 140.0, 40.0, "Header", 0, 0, 0)]
    assert document.closed
    assert calls["pixmap"] == 1
    assert session.diagnostics()["cache_hits"] == 1


def test_failure_has_context_and_opens_circuit_for_later_pages():
    page, roi, fitz, _document, calls = fixtures(failure=RuntimeError("no tesseract"))
    session = RoiOcrSession(disable_after_failure=True)
    with pytest.raises(RoiOcrError, match="page 2"):
        session.words(page, roi, fitz)
    page.number = 2
    with pytest.raises(RoiOcrError, match="circuit open"):
        session.words(page, roi, fitz)
    assert calls["pixmap"] == 1
    diagnostics = session.diagnostics()
    assert diagnostics["attempts"] == 1
    assert diagnostics["circuit_open"]
    assert diagnostics["failures"][0]["error"] == "RuntimeError: no tesseract"
    assert diagnostics["failures"][0]["category"] == "dependency_unavailable"
    assert diagnostics["skipped_by_circuit"] == 1


def test_page_local_failure_does_not_disable_other_pages():
    page, roi, fitz, _document, calls = fixtures(failure=ValueError("bad page image"))
    session = RoiOcrSession(disable_after_failure=True)
    with pytest.raises(RoiOcrError) as first:
        session.words(page, roi, fitz)
    assert first.value.category == "page_ocr_failure"
    assert first.value.retryable
    page.number = 2
    with pytest.raises(RoiOcrError) as second:
        session.words(page, roi, fitz)
    assert second.value.category == "page_ocr_failure"
    assert calls["pixmap"] == 2
    assert not session.diagnostics()["circuit_open"]


@pytest.mark.parametrize(
    "roi",
    [
        SimpleNamespace(x0=1, y0=0, x1=1, y1=2, width=0, height=2),
        SimpleNamespace(x0=float("nan"), y0=0, x1=1, y1=2, width=1, height=2),
    ],
)
def test_invalid_roi_is_rejected_before_rendering(roi):
    page, _roi, fitz, _document, calls = fixtures()
    with pytest.raises(ValueError, match="ROI"):
        RoiOcrSession().words(page, roi, fitz)
    assert calls["pixmap"] == 0


def test_cache_can_be_disabled_for_debugging():
    page, roi, fitz, _document, calls = fixtures()
    session = RoiOcrSession(cache_enabled=False)
    session.words(page, roi, fitz)
    session.words(page, roi, fitz)
    assert calls["pixmap"] == 2
