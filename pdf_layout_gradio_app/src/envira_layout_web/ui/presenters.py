"""Narrow presentation adapters for persistent pipeline artifacts."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def load_overlay_image(path: str | Path) -> Image.Image:
    """Load one persisted overlay as RGB pixels safe for Gradio caching."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Overlay image is unavailable: {path}")
    with Image.open(source) as image:
        return image.convert("RGB").copy()
