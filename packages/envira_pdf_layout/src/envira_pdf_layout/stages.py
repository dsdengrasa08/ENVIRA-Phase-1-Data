"""Small contracts used while extracting stages from the preserved core."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .types import LayoutRegion, TransformStageResult


@dataclass(frozen=True)
class StageContext:
    """Shared immutable inputs available to independently testable stages."""

    pages: list[dict[str, Any]]
    config: Any
    metadata: dict[str, Any] = field(default_factory=dict)


class TransformStage(Protocol):
    """Contract for a named, side-effect-free region transformation."""

    name: str

    def __call__(
        self, regions: list[LayoutRegion], context: StageContext
    ) -> TransformStageResult: ...
