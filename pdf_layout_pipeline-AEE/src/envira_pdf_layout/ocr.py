"""Explicit optional OCR-provider boundary for caption validation."""

from __future__ import annotations

from importlib import import_module

from .config import CaptionOCRConfig


def create_caption_line_provider(config: CaptionOCRConfig):
    """Load ``package.module:factory`` or ``package.module:callable`` on demand."""
    if not config.enabled:
        return None
    if ":" not in config.provider:
        raise ValueError(
            "caption_ocr.provider must use 'package.module:attribute' syntax"
        )
    module_name, attribute = config.provider.split(":", 1)
    provider = getattr(import_module(module_name), attribute)
    candidate = (
        provider() if getattr(provider, "is_provider_factory", False) else provider
    )
    if not callable(candidate):
        raise TypeError(f"Caption OCR provider is not callable: {config.provider}")
    return candidate
