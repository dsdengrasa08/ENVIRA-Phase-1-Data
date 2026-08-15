from pathlib import Path


def test_ui_is_overlay_only():
    source = (Path(__file__).resolve().parents[1] / "src/envira_gradio/ui/builder.py").read_text()
    assert "gr.File" in source
    assert "gr.Gallery" in source
    for forbidden in ("gr.JSON", "gr.Dataframe", "gr.AnnotatedImage", "gr.FileExplorer"):
        assert forbidden not in source
