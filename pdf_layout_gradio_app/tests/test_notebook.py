import json
from pathlib import Path


def test_launcher_is_lightweight_and_independent():
    root = Path(__file__).resolve().parents[1]
    notebook = json.loads((root / "run_gradio_web_app.ipynb").read_text(encoding="utf-8"))
    source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])
    assert "create_app" in source
    assert "drive.mount" in source
    assert "run_layout_pipeline" not in source
    assert "pdf_layout_pipeline-AEE-vWiP" not in source
