import json
from pathlib import Path


def test_launcher_is_lightweight_and_independent():
    root = Path(__file__).resolve().parents[1]
    notebook = json.loads((root / "run_gradio_web_app.ipynb").read_text(encoding="utf-8"))
    source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])
    assert "create_app" in source
    assert "drive.mount" in source
    assert 'sys.executable, "-m", "pip"' in source
    assert 'APP_DIR / "src"' in source
    assert "sys.path.insert(0, standalone_src)" in source
    assert 'find_spec("envira_layout_web")' in source
    assert ".launch(share=True)" in source
    assert "launch_notebook_app" not in source
    assert "proxyPort" not in source
    assert "server_port" not in source
    assert "debug=IN_COLAB" not in source
    assert "run_layout_pipeline" not in source
    assert "pdf_layout_pipeline-AEE-vWiP" not in source
    assert "Gradio share service was unavailable" not in source
    assert all(not cell.get("outputs") for cell in notebook["cells"])
