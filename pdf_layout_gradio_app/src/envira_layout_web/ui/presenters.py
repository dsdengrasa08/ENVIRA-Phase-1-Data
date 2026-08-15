"""Narrow presentation adapters for persistent pipeline artifacts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image


def load_overlay_image(path: str | Path) -> Image.Image:
    """Load one persisted overlay as RGB pixels safe for Gradio caching."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Overlay image is unavailable: {path}")
    with Image.open(source) as image:
        return image.convert("RGB").copy()


def load_overlay_pixels(path: str | Path) -> NDArray[np.uint8]:
    """Return an overlay without retaining its persistent Drive path.

    Gradio treats strings and path-bearing objects as files and rejects files
    outside its cache, working directory, and system temporary directory.  A
    copied pixel array has no source-path metadata, so Gallery writes its own
    presentation copy to the Gradio cache while the pipeline artifact remains
    persisted on Drive.
    """
    return np.asarray(load_overlay_image(path), dtype=np.uint8).copy()
