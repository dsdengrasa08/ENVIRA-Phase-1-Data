from pathlib import Path

import envira_pdf_layout.authoritative as compatibility
import envira_pdf_layout.independent_core as independent_core
import envira_pdf_layout.pipeline as pipeline


PACKAGE = Path(__file__).parents[1] / "src" / "envira_pdf_layout"


def test_production_pipeline_uses_package_owned_core():
    source = (PACKAGE / "pipeline.py").read_text(encoding="utf-8")
    assert "from .independent_core import run_independent_core" in source
    assert "run_independent_core(conversion, page_set, config)" in source
    assert "run_authoritative_pipeline" not in source


def test_runtime_modules_do_not_load_or_execute_a_notebook():
    for filename in ("pipeline.py", "authoritative.py", "independent_core.py"):
        source = (PACKAGE / filename).read_text(encoding="utf-8")
        assert "json.loads" not in source
        assert "_REFERENCE_CELLS" not in source
        assert "reference-cell-" not in source
        assert "exec(" not in source


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
