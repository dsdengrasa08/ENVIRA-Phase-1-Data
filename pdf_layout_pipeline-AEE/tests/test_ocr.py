import pytest

from envira_pdf_layout.config import CaptionOCRConfig
from envira_pdf_layout.ocr import create_caption_line_provider


def test_caption_ocr_is_explicitly_disabled_by_default():
    assert create_caption_line_provider(CaptionOCRConfig()) is None


def test_caption_ocr_provider_path_is_validated():
    with pytest.raises(ValueError, match="package.module:attribute"):
        create_caption_line_provider(CaptionOCRConfig(enabled=True, provider="invalid"))
