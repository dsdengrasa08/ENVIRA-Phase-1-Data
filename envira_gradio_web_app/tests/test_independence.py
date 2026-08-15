from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_has_no_reference_implementation_dependency():
    forbidden = ("pdf_layout_pipeline-AEE-vWiP", "envira_pdf_layout")
    inspected = [
        *sorted((APP_ROOT / "src").rglob("*.py")),
        APP_ROOT / "requirements.txt",
        APP_ROOT / "pyproject.toml",
        APP_ROOT / "run_gradio_web_app.ipynb",
    ]
    offenders = [
        str(path.relative_to(APP_ROOT))
        for path in inspected
        if any(value in path.read_text() for value in forbidden)
    ]
    assert offenders == []


def test_standalone_package_contains_runtime_resources():
    resources = APP_ROOT / "src" / "envira_gradio" / "pipeline" / "resources"
    assert (resources / "default.yaml").is_file()
    assert (resources / "layout-region-v1.schema.json").is_file()
