from pathlib import Path

from PIL import Image
import pytest

from envira_layout_web.ui.presenters import load_overlay_image


def test_load_overlay_image_returns_rgb_pixels(tmp_path: Path):
    overlay = tmp_path / "overlay.png"
    Image.new("RGB", (1, 1), (250, 2, 1)).save(overlay)

    rgb = load_overlay_image(overlay)

    assert rgb.getpixel((0, 0)) == (250, 2, 1)


def test_load_overlay_image_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="Overlay image is unavailable"):
        load_overlay_image(tmp_path / "missing.png")
