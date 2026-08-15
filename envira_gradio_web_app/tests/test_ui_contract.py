from pathlib import Path

import gradio as gr
from PIL import Image


def test_ui_is_overlay_only():
    source = (Path(__file__).resolve().parents[1] / "src/envira_gradio/ui/builder.py").read_text()
    assert "gr.File" in source
    assert "gr.Gallery" in source
    for forbidden in ("gr.JSON", "gr.Dataframe", "gr.AnnotatedImage", "gr.FileExplorer"):
        assert forbidden not in source


def test_gallery_postprocesses_detached_images_without_drive_paths():
    value = [(Image.new("RGB", (10, 10), "white"), "Page 1")]

    result = gr.Gallery().postprocess(value)

    assert len(result.root) == 1
    assert result.root[0].caption == "Page 1"
