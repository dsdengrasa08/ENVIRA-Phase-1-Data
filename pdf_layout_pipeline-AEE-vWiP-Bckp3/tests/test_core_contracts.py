from types import SimpleNamespace

import pytest

from envira_pdf_layout.config import PipelineConfig
from envira_pdf_layout.core_contracts import (
    CoreCapabilities,
    StageOutput,
    compare_core_results,
    legacy_environment_report,
    execute_core_stage,
    StageInvariantError,
)


def result(bbox=(0, 0, 10, 10)):
    region = {"layout_region_id": "r1", "bbox_px": list(bbox)}
    return SimpleNamespace(
        raw_regions=[region], final_regions=[region], excluded_by_stage={"stage": []}
    )


def test_stage_output_uses_immutable_collection_boundaries():
    output = StageOutput(regions=({"layout_region_id": "r1"},))
    assert isinstance(output.regions, tuple)
    assert output.excluded == ()


def test_semantic_core_comparison_reports_geometry_differences():
    assert compare_core_results(result(), result())["equivalent"]
    comparison = compare_core_results(result(), result((0, 0, 20, 20)))
    assert not comparison["equivalent"]
    assert "final_geometry" in comparison["differences"]


def test_capability_contract_is_explicit_and_serializable():
    capabilities = CoreCapabilities("preserved", True, False, False, False)
    assert capabilities.to_dict()["processing_side_effect_free"] is False


def test_core_selector_validation():
    assert PipelineConfig.load(environ={}, core={"implementation": "shadow_compare"}).core.implementation == "shadow_compare"
    try:
        PipelineConfig.load(environ={}, core={"implementation": "unknown"})
    except ValueError as exc:
        assert "core.implementation" in str(exc)
    else:
        raise AssertionError("unknown core implementation was accepted")


def test_legacy_environment_report_flags_unmapped_compatibility_values():
    config = PipelineConfig.load(
        environ={"PHASE1_PAGE_START": "2", "PHASE1_UNKNOWN_LEGACY": "value"}
    )
    report = legacy_environment_report(config)
    assert report["translated_to_typed_config"] == ["PHASE1_PAGE_START"]
    assert report["compatibility_only"] == ["PHASE1_UNKNOWN_LEGACY"]
    assert report["ambient_environment_reads"] is False


def test_stage_runner_enforces_partition_and_stable_ids():
    class Keep:
        name = "keep"

        def __call__(self, inputs, regions):
            return StageOutput(regions=tuple(regions))

    regions = [{"layout_region_id": "r1", "bbox_px": [0, 0, 1, 1]}]
    assert execute_core_stage(Keep(), None, regions).regions[0]["layout_region_id"] == "r1"

    class Invent:
        name = "invent"

        def __call__(self, inputs, regions):
            return StageOutput(regions=({"layout_region_id": "new"},))

    with pytest.raises(StageInvariantError, match="lost or invented"):
        execute_core_stage(Invent(), None, regions)
