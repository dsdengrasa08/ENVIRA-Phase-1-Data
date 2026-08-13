"""Orientation metadata and local-coordinate geometry for semantic relations."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable


_RIGHT_ANGLES = (0.0, 90.0, 180.0, 270.0)


def normalize_angle(value: Any) -> float | None:
    """Return a clockwise page angle in ``[0, 360)`` when one is available."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("angle_degrees", value.get("angle", value.get("rotation")))
    try:
        angle = float(value) % 360.0
    except (TypeError, ValueError):
        return None
    return angle if math.isfinite(angle) else None


def angular_distance(left: float, right: float) -> float:
    delta = abs((left - right) % 360.0)
    return min(delta, 360.0 - delta)


def region_orientation(region: dict[str, Any]) -> dict[str, Any]:
    """Read preserved orientation or conservatively infer its dominant axis.

    Aspect-ratio inference deliberately reports only an axis, not a clockwise
    reading direction: an axis-aligned rectangle cannot distinguish 90 from 270.
    """
    raw = region.get("orientation")
    angle = normalize_angle(raw)
    if angle is not None:
        confidence = float(raw.get("confidence", 1.0)) if isinstance(raw, dict) else 1.0
        source = raw.get("source", "upstream") if isinstance(raw, dict) else "upstream"
        return {"angle_degrees": angle, "confidence": confidence, "source": source}
    for key in ("orientation_degrees", "rotation", "angle"):
        angle = normalize_angle(region.get(key))
        if angle is not None:
            return {"angle_degrees": angle, "confidence": 0.9, "source": key}
    box = region.get("bbox_px") or []
    if len(box) == 4 and region.get("type") in {"Text", "Caption", "List", "Footnote"}:
        width = max(1.0, float(box[2]) - float(box[0]))
        height = max(1.0, float(box[3]) - float(box[1]))
        if height / width >= 2.0:
            return {"angle_degrees": 90.0, "confidence": 0.45, "source": "bbox_axis"}
        if width / height >= 2.0:
            return {"angle_degrees": 0.0, "confidence": 0.45, "source": "bbox_axis"}
    return {"angle_degrees": None, "confidence": 0.0, "source": "unknown"}


def compatible_orientation(
    left: dict[str, Any], right: dict[str, Any], *, tolerance_degrees: float = 12.0
) -> bool | None:
    """Return compatibility, or ``None`` when either direction is unknown."""
    a = region_orientation(left)["angle_degrees"]
    b = region_orientation(right)["angle_degrees"]
    if a is None or b is None:
        return None
    # Baseline-axis compatibility treats reverse reading directions as parallel.
    distance = min(angular_distance(a, b), angular_distance((a + 180.0) % 360.0, b))
    return distance <= tolerance_degrees


@dataclass(frozen=True)
class LocalBox:
    inline_min: float
    block_min: float
    inline_max: float
    block_max: float

    @property
    def inline_size(self) -> float:
        return self.inline_max - self.inline_min

    @property
    def block_size(self) -> float:
        return self.block_max - self.block_min


def project_bbox(bbox: Iterable[float], angle_degrees: float) -> LocalBox:
    """Project a page bbox onto an orientation-normalized inline/block frame."""
    x0, y0, x1, y1 = map(float, bbox)
    radians = math.radians(angle_degrees)
    inline = (math.cos(radians), math.sin(radians))
    block = (-math.sin(radians), math.cos(radians))
    points = ((x0, y0), (x0, y1), (x1, y0), (x1, y1))
    inline_values = [x * inline[0] + y * inline[1] for x, y in points]
    block_values = [x * block[0] + y * block[1] for x, y in points]
    return LocalBox(min(inline_values), min(block_values), max(inline_values), max(block_values))


def interval_overlap_ratio(a0: float, a1: float, b0: float, b1: float) -> float:
    overlap = max(0.0, min(a1, b1) - max(a0, b0))
    return overlap / max(1.0, min(a1 - a0, b1 - b0))


def local_relation(
    candidate: Iterable[float], anchor: Iterable[float], angle: float
) -> dict[str, Any]:
    """Describe candidate placement around an anchor in normalized coordinates."""
    cb, ab = project_bbox(candidate, angle), project_bbox(anchor, angle)
    sides = {
        "before": (
            cb.block_max <= ab.block_min,
            max(0.0, ab.block_min - cb.block_max),
            interval_overlap_ratio(
                cb.inline_min, cb.inline_max, ab.inline_min, ab.inline_max
            ),
        ),
        "after": (
            cb.block_min >= ab.block_max,
            max(0.0, cb.block_min - ab.block_max),
            interval_overlap_ratio(
                cb.inline_min, cb.inline_max, ab.inline_min, ab.inline_max
            ),
        ),
        "inline_before": (
            cb.inline_max <= ab.inline_min,
            max(0.0, ab.inline_min - cb.inline_max),
            interval_overlap_ratio(
                cb.block_min, cb.block_max, ab.block_min, ab.block_max
            ),
        ),
        "inline_after": (
            cb.inline_min >= ab.inline_max,
            max(0.0, cb.inline_min - ab.inline_max),
            interval_overlap_ratio(
                cb.block_min, cb.block_max, ab.block_min, ab.block_max
            ),
        ),
    }
    possible = [(name, values) for name, values in sides.items() if values[0]]
    if not possible:
        return {"side": None, "gap": 0.0, "overlap": 0.0, "candidate": cb, "anchor": ab}
    side, (_, gap, overlap) = min(possible, key=lambda item: item[1][1])
    return {"side": side, "gap": gap, "overlap": overlap, "candidate": cb, "anchor": ab}


def canonical_right_angle(angle: float) -> float:
    return min(_RIGHT_ANGLES, key=lambda candidate: angular_distance(angle, candidate))
