"""Versioned region, relationship, and geometry lifecycle contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
from typing import Any, Literal

from .geometry import clip_bbox

REGION_SCHEMA_VERSION = 1
RELATIONSHIP_SCHEMA_VERSION = 1
GEOMETRY_HISTORY_SCHEMA_VERSION = 1
COMPLETION_PROPOSAL_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class BBoxValue:
    x0: float
    y0: float
    x1: float
    y1: float
    coordinate_space: Literal["page_px", "page_pt", "normalized"] = "page_px"
    origin: Literal["top_left", "bottom_left"] = "top_left"

    @classmethod
    def from_value(cls, value: Any, **metadata: Any) -> "BBoxValue":
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ValueError("bbox must contain exactly four coordinates")
        result = cls(*(float(item) for item in value), **metadata)
        if not result.is_valid:
            raise ValueError(f"bbox must be finite with positive area: {value!r}")
        return result

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    @property
    def is_valid(self) -> bool:
        return (
            all(math.isfinite(value) for value in self.to_tuple())
            and self.width > 0
            and self.height > 0
        )

    def to_tuple(self) -> tuple[float, float, float, float]:
        return self.x0, self.y0, self.x1, self.y1

    def to_list(self) -> list[float]:
        return list(self.to_tuple())

    def clipped(self, width: float, height: float) -> "BBoxValue":
        return BBoxValue.from_value(
            clip_bbox(self.to_tuple(), width, height),
            coordinate_space=self.coordinate_space,
            origin=self.origin,
        )


@dataclass(frozen=True, slots=True)
class GeometryEvent:
    geometry_history_schema_version: int
    geometry_version: int
    stage: str
    reason: str
    source_bbox_px: list[float]
    proposed_bbox_px: list[float]
    resolved_bbox_px: list[float]
    accepted: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def refresh_geometry_metrics(region: dict[str, Any]) -> None:
    bbox = BBoxValue.from_value(region["bbox_px"])
    region["width_px"] = bbox.width
    region["height_px"] = bbox.height
    region["area_px"] = bbox.area


def initialize_region_schema(
    region: dict[str, Any], *, page_record: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Populate the versioned compatibility schema without changing stable IDs."""
    region["region_schema_version"] = REGION_SCHEMA_VERSION
    bbox = BBoxValue.from_value(region["bbox_px"])
    region.setdefault("source_bbox_px", bbox.to_list())
    region.setdefault("resolved_bbox_px", bbox.to_list())
    region.setdefault("physical_bbox_px", list(region["resolved_bbox_px"]))
    region.setdefault("visual_crop_bbox_px", list(region["resolved_bbox_px"]))
    region.setdefault("semantic_group_bbox_px", list(region["resolved_bbox_px"]))
    region.setdefault("geometry_version", 1)
    if not region.get("geometry_history"):
        region["geometry_history"] = [
            GeometryEvent(
                GEOMETRY_HISTORY_SCHEMA_VERSION,
                int(region.get("geometry_version") or 1),
                "region_conversion",
                "source_geometry",
                list(region["source_bbox_px"]),
                list(region["source_bbox_px"]),
                list(region["resolved_bbox_px"]),
                True,
            ).to_dict()
        ]
    region["coordinate_space"] = {
        "units": "px",
        "origin": "top_left",
        "page_number": int(region["page_number"]),
        "render_dpi": page_record.get("render_dpi") if page_record else None,
        "page_width": (page_record.get("image_width_px") if page_record else None),
        "page_height": (page_record.get("image_height_px") if page_record else None),
    }
    refresh_geometry_metrics(region)
    return region


def apply_geometry_change(
    region: dict[str, Any],
    proposed_bbox: Any,
    *,
    stage: str,
    reason: str,
    accepted: bool,
    page_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply one geometry proposal and atomically maintain metrics and history."""
    initialize_region_schema(region, page_record=page_record)
    source = BBoxValue.from_value(region["resolved_bbox_px"])
    proposal = BBoxValue.from_value(proposed_bbox)
    if page_record:
        width = float(
            page_record.get("image_width_px") or page_record.get("width_px") or 0
        )
        height = float(
            page_record.get("image_height_px") or page_record.get("height_px") or 0
        )
        if width > 0 and height > 0:
            proposal = proposal.clipped(width, height)
    resolved = proposal if accepted else source
    old_version = int(region.get("geometry_version") or 1)
    new_version = (
        old_version + 1
        if accepted and resolved.to_list() != source.to_list()
        else old_version
    )
    region["proposed_bbox_px"] = proposal.to_list()
    region["resolved_bbox_px"] = resolved.to_list()
    region["physical_bbox_px"] = resolved.to_list()
    region["bbox_px"] = resolved.to_list()
    region["geometry_version"] = new_version
    history = list(region.get("geometry_history") or [])
    history.append(
        GeometryEvent(
            GEOMETRY_HISTORY_SCHEMA_VERSION,
            new_version,
            stage,
            reason,
            source.to_list(),
            proposal.to_list(),
            resolved.to_list(),
            accepted,
        ).to_dict()
    )
    region["geometry_history"] = history
    refresh_geometry_metrics(region)
    return region


def validate_region_schema(
    region: dict[str, Any], page_record: dict[str, Any] | None = None
) -> list[str]:
    errors = []
    if region.get("region_schema_version") != REGION_SCHEMA_VERSION:
        errors.append("unsupported_region_schema")
    for key in ("layout_region_id", "page_number", "type", "bbox_px"):
        missing = (
            "bbox_px" not in region
            if key == "bbox_px"
            else region.get(key) in {None, ""}
        )
        if missing:
            errors.append(f"missing_{key}")
    try:
        bbox = BBoxValue.from_value(region.get("bbox_px"))
    except (TypeError, ValueError):
        return errors + ["invalid_bbox"]
    if page_record:
        width = float(
            page_record.get("image_width_px") or page_record.get("width_px") or 0
        )
        height = float(
            page_record.get("image_height_px") or page_record.get("height_px") or 0
        )
        if (
            width > 0
            and height > 0
            and (bbox.x0 < 0 or bbox.y0 < 0 or bbox.x1 > width or bbox.y1 > height)
        ):
            errors.append("bbox_outside_page")
    expected = (bbox.width, bbox.height, bbox.area)
    actual = (region.get("width_px"), region.get("height_px"), region.get("area_px"))
    if any(value is None for value in actual) or any(
        not math.isclose(float(left), right, rel_tol=1e-9, abs_tol=1e-6)
        for left, right in zip(actual, expected)
    ):
        errors.append("derived_geometry_mismatch")
    if region.get("bbox_px") != region.get("resolved_bbox_px") or region.get(
        "bbox_px"
    ) != region.get("physical_bbox_px"):
        errors.append("physical_geometry_alias_mismatch")
    coordinate_space = region.get("coordinate_space") or {}
    if coordinate_space.get("units") != "px" or coordinate_space.get("origin") != "top_left":
        errors.append("unsupported_coordinate_space")
    history = region.get("geometry_history") or []
    if not history:
        errors.append("missing_geometry_history")
    else:
        if any(
            event.get("geometry_history_schema_version")
            != GEOMETRY_HISTORY_SCHEMA_VERSION
            for event in history
        ):
            errors.append("unsupported_geometry_history_schema")
        final = history[-1]
        if final.get("geometry_version") != region.get("geometry_version") or final.get(
            "resolved_bbox_px"
        ) != region.get("bbox_px"):
            errors.append("geometry_history_mismatch")
    return errors


def normalize_relationship_schema(relationship: dict[str, Any]) -> dict[str, Any]:
    relationship.setdefault("relationship_schema_version", RELATIONSHIP_SCHEMA_VERSION)
    relationship.setdefault("geometry_version", 1)
    return relationship


def migrate_region(
    region: dict[str, Any], *, to_version: int = REGION_SCHEMA_VERSION
) -> dict[str, Any]:
    if to_version != REGION_SCHEMA_VERSION:
        raise ValueError(f"unsupported target region schema: {to_version}")
    current = region.get("region_schema_version")
    if current not in {None, REGION_SCHEMA_VERSION}:
        raise ValueError(f"unsupported source region schema: {current}")
    return initialize_region_schema(deepcopy(region))
