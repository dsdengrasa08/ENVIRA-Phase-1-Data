from types import SimpleNamespace

import pytest

import envira_pdf_layout.independent_core as dispatcher
from envira_pdf_layout.preserved_core import _temporary_environment
from envira_pdf_layout.config import PipelineConfig


def fake_result():
    region = {"layout_region_id": "r1", "bbox_px": [0, 0, 1, 1]}
    return SimpleNamespace(
        diagnostics={}, raw_regions=[region], final_regions=[region], excluded_by_stage={}
    )


def test_preserved_mode_publishes_honest_capabilities(monkeypatch):
    monkeypatch.setattr(dispatcher, "run_preserved_core", lambda *_: fake_result())
    result = dispatcher.run_independent_core(
        None, None, PipelineConfig.load(environ={}, core={"implementation": "preserved"})
    )
    capabilities = result.diagnostics["core_capabilities"]
    assert capabilities["implementation"] == "preserved"
    assert capabilities["reentrant"] is False
    assert capabilities["processing_side_effect_free"] is False


def test_shadow_compare_fails_closed_on_semantic_difference(monkeypatch):
    calls = []

    def preserved(*_):
        calls.append("preserved")
        return fake_result()

    def extracted(*_):
        calls.append("extracted")
        value = fake_result()
        value.final_regions[0]["bbox_px"] = [0, 0, 2, 2]
        return value

    monkeypatch.setattr(dispatcher, "run_preserved_core", preserved)
    monkeypatch.setattr(dispatcher, "run_extracted_core", extracted)
    config = PipelineConfig.load(
        environ={},
        core={"implementation": "shadow_compare", "fail_on_difference": True},
    )
    with pytest.raises(RuntimeError, match="shadow comparison diverged"):
        dispatcher.run_independent_core(None, None, config)
    assert calls == ["preserved", "extracted"]


def test_preserved_environment_bridge_restores_all_runtime_values(monkeypatch):
    monkeypatch.setenv("HF_HOME", "original")
    monkeypatch.setenv("PHASE1_PAGE_START", "99")
    with _temporary_environment({"PHASE1_PAGE_START": "2"}):
        assert __import__("os").environ["PHASE1_PAGE_START"] == "2"
        __import__("os").environ["HF_HOME"] = "temporary"
    assert __import__("os").environ["HF_HOME"] == "original"
    assert __import__("os").environ["PHASE1_PAGE_START"] == "99"
