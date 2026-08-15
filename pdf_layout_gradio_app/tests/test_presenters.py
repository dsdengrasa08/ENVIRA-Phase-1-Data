from pathlib import Path

import gradio as gr
from PIL import Image
import pytest

from envira_layout_web.ui.presenters import load_overlay_image, load_overlay_pixels


def test_load_overlay_image_returns_rgb_pixels(tmp_path: Path):
    overlay = tmp_path / "overlay.png"
    Image.new("RGB", (1, 1), (250, 2, 1)).save(overlay)

    rgb = load_overlay_image(overlay)

    assert rgb.getpixel((0, 0)) == (250, 2, 1)


def test_load_overlay_image_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Overlay image is unavailable"):
        load_overlay_image(tmp_path / "missing.png")


def test_load_overlay_pixels_has_no_persistent_path_metadata(tmp_path: Path):
    overlay = tmp_path / "drive" / "overlay.png"
    overlay.parent.mkdir()
    Image.new("RGB", (1, 1), (3, 4, 5)).save(overlay)

    pixels = load_overlay_pixels(overlay)

    assert pixels.tolist() == [[[3, 4, 5]]]
    assert not hasattr(pixels, "filename")

    gallery_value = gr.Gallery().postprocess([(pixels, "Page 1")])
    cached = Path(gallery_value.root[0].image.path)
    assert cached.is_file()
    assert not cached.is_relative_to(overlay.parent)
