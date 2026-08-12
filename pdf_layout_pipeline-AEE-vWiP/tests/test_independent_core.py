from pathlib import Path

import envira_pdf_layout.authoritative as compatibility
import envira_pdf_layout.independent_core as independent_core
import envira_pdf_layout.pipeline as pipeline


PACKAGE = Path(__file__).parents[1] / "src" / "envira_pdf_layout"
PROJECT = Path(__file__).parents[1]


def test_production_pipeline_uses_package_owned_core():
    source = (PACKAGE / "pipeline.py").read_text(encoding="utf-8")
    assert "from .independent_core import run_independent_core" in source
    assert "run_independent_core(conversion, page_set, config)" in source
    assert "run_authoritative_pipeline" not in source


def test_production_core_uses_extracted_region_conversion_stage():
    source = (PACKAGE / "independent_core.py").read_text(encoding="utf-8")
    assert "from .region_conversion import convert_docling_document" in source
    assert "conversion_result = convert_docling_document(" in source
    assert "def docling_item_to_regions" not in source
    assert "def iter_docling_items" not in source


def test_runtime_modules_do_not_load_or_execute_a_notebook():
    for filename in ("pipeline.py", "authoritative.py", "independent_core.py"):
        source = (PACKAGE / filename).read_text(encoding="utf-8")
        assert "json.loads" not in source
        assert "_REFERENCE_CELLS" not in source
        assert "reference-cell-" not in source
        assert "exec(" not in source


def test_project_has_no_source_notebook_dependency():
    forbidden = ("source_pdf_" + "layoutparser", "pdf_layoutparser_" + "vF.ipynb")
    text_files = [
        path
        for path in PROJECT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and "__pycache__" not in path.parts
        and path.suffix in {".py", ".md", ".yaml", ".yml", ".ipynb", ".txt"}
    ]
    references = {
        str(path.relative_to(PROJECT)): token
        for path in text_files
        for token in forbidden
        if token in path.read_text(encoding="utf-8")
    }
    assert references == {}


def test_compatibility_entry_point_delegates_to_independent_core(monkeypatch):
    expected = object()
    received = []

    def fake_core(conversion, page_set, config):
        received.append((conversion, page_set, config))
        return expected

    monkeypatch.setattr(compatibility, "run_independent_core", fake_core)
    assert compatibility.run_authoritative_pipeline("c", "p", "cfg") is expected
    assert received == [("c", "p", "cfg")]


def test_independent_core_is_importable_without_reference_notebook():
    assert callable(independent_core.run_independent_core)
    assert callable(pipeline.run_layout_pipeline)
