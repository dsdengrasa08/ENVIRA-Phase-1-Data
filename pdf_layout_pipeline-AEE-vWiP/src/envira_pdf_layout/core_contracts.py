"""Typed, immutable contracts for incremental core-stage extraction."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict
import hashlib
import json
from typing import Any, Mapping, Protocol, Sequence

from .config import PipelineConfig
from .types import DocumentIdentity, LayoutRegion, PageRecord, PipelineResult


@dataclass(frozen=True)
class CoreInputs:
    document: DocumentIdentity
    pages: tuple[PageRecord, ...]
    converted_regions: tuple[LayoutRegion, ...]
    raw_document: Mapping[str, Any]
    raw_markdown: str
    config: PipelineConfig


@dataclass(frozen=True)
class StageOutput:
    regions: tuple[LayoutRegion, ...]
    excluded: tuple[LayoutRegion, ...] = ()
    relationships: tuple[Mapping[str, Any], ...] = ()
    decisions: tuple[Mapping[str, Any], ...] = ()
    diagnostics: Mapping[str, Any] | None = None


class CoreStage(Protocol):
    name: str

    def __call__(self, inputs: CoreInputs, regions: Sequence[LayoutRegion]) -> StageOutput: ...


class StageInvariantError(RuntimeError):
    pass


def execute_core_stage(
    stage: CoreStage, inputs: CoreInputs, regions: Sequence[LayoutRegion]
) -> StageOutput:
    """Run a pure stage and enforce immutable input and stable-ID contracts."""
    before = _region_digest(regions)
    output = stage(inputs, tuple(deepcopy(list(regions))))
    if _region_digest(regions) != before:
        raise StageInvariantError(f"{stage.name} mutated its input collection")
    output_ids = [str(row["layout_region_id"]) for row in output.regions]
    excluded_ids = [str(row["layout_region_id"]) for row in output.excluded]
    if len(output_ids) != len(set(output_ids)):
        raise StageInvariantError(f"{stage.name} produced duplicate region IDs")
    input_ids = {str(row["layout_region_id"]) for row in regions}
    if set(output_ids) | set(excluded_ids) != input_ids:
        raise StageInvariantError(f"{stage.name} lost or invented region IDs")
    return output


def _region_digest(regions: Sequence[LayoutRegion]) -> str:
    payload = json.dumps(list(regions), sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class CoreCapabilities:
    implementation: str
    thread_safe: bool
    reentrant: bool
    process_environment_isolated: bool
    processing_side_effect_free: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _signature(result: PipelineResult) -> dict[str, Any]:
    return {
        "raw_ids": sorted(str(row["layout_region_id"]) for row in result.raw_regions),
        "final_ids": sorted(str(row["layout_region_id"]) for row in result.final_regions),
        "excluded_ids": {
            stage: sorted(str(row["layout_region_id"]) for row in rows)
            for stage, rows in sorted(result.excluded_by_stage.items())
        },
        "final_geometry": {
            str(row["layout_region_id"]): list(row["bbox_px"])
            for row in result.final_regions
        },
    }


def compare_core_results(left: PipelineResult, right: PipelineResult) -> dict[str, Any]:
    """Compare semantic core outputs, deliberately ignoring paths and elapsed time."""
    left_signature, right_signature = _signature(left), _signature(right)
    differences = {
        key: {"preserved": left_signature[key], "extracted": right_signature[key]}
        for key in left_signature
        if left_signature[key] != right_signature[key]
    }
    return {"equivalent": not differences, "differences": differences}


def legacy_environment_report(config: PipelineConfig) -> dict[str, Any]:
    """Classify captured legacy variables without reading ambient process state."""
    translated = {
        source.removeprefix("environment:")
        for source in config.value_sources.values()
        if source.startswith("environment:PHASE1_")
    }
    captured = set(config.legacy_core_environment)
    return {
        "captured": sorted(captured),
        "translated_to_typed_config": sorted(captured & translated),
        "compatibility_only": sorted(captured - translated),
        "ambient_environment_reads": False,
    }
