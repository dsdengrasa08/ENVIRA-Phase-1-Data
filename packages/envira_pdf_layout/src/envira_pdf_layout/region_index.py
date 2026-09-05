"""Immutable indexes and derived text features for one region collection."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, Mapping

from .types import LayoutRegion


@dataclass(frozen=True)
class RegionTextFeatures:
    normalized_text: str
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class RegionIndex:
    by_id: Mapping[str, LayoutRegion]
    by_page: Mapping[int, tuple[LayoutRegion, ...]]
    by_page_and_type: Mapping[int, Mapping[str, tuple[LayoutRegion, ...]]]
    page_sizes: Mapping[int, tuple[float, float]]
    text_features: Mapping[str, RegionTextFeatures]

    @classmethod
    def build(
        cls, regions: list[LayoutRegion], pages: list[dict[str, Any]]
    ) -> "RegionIndex":
        by_page: dict[int, list[LayoutRegion]] = defaultdict(list)
        by_type: dict[int, dict[str, list[LayoutRegion]]] = defaultdict(
            lambda: defaultdict(list)
        )
        by_id: dict[str, LayoutRegion] = {}
        text_features: dict[str, RegionTextFeatures] = {}
        for region in regions:
            region_id = str(region["layout_region_id"])
            page_number = int(region["page_number"])
            kind = str(region.get("type") or "Unknown")
            by_id[region_id] = region
            by_page[page_number].append(region)
            by_type[page_number][kind].append(region)
            normalized = re.sub(
                r"\W+",
                " ",
                str(region.get("text") or region.get("orig") or "").casefold(),
            ).strip()
            text_features[region_id] = RegionTextFeatures(
                normalized, tuple(normalized.split())
            )
        sizes = {
            int(page["page_number"]): (
                float(page.get("image_width_px") or page.get("width_px") or 1),
                float(page.get("image_height_px") or page.get("height_px") or 1),
            )
            for page in pages
        }
        frozen_types = {
            page: MappingProxyType(
                {kind: tuple(values) for kind, values in groups.items()}
            )
            for page, groups in by_type.items()
        }
        return cls(
            MappingProxyType(by_id),
            MappingProxyType({page: tuple(values) for page, values in by_page.items()}),
            MappingProxyType(frozen_types),
            MappingProxyType(sizes),
            MappingProxyType(text_features),
        )

    def types(self, page_number: int, *kinds: str) -> tuple[LayoutRegion, ...]:
        page_types = self.by_page_and_type.get(page_number, {})
        return tuple(region for kind in kinds for region in page_types.get(kind, ()))
