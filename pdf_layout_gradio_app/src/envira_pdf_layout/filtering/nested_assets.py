"""Remove duplicate layout elements contained within Figure/Table parents."""

from ..geometry import coverage
from ..types import FilterStageResult


def filter_nested_asset_elements(regions, page_map):
    assets = [r for r in regions if r["type"] in {"Figure", "Table"}]
    drop = {}
    for region in regions:
        if region in assets:
            continue
        for asset in assets:
            if (
                region["page_number"] == asset["page_number"]
                and coverage(tuple(region["bbox_px"]), tuple(asset["bbox_px"])) >= 0.92
            ):
                drop[region["layout_region_id"]] = (
                    f"nested_inside_{asset['type'].lower()}"
                )
                break
    excluded = [
        {**r, "filter_reason": drop[r["layout_region_id"]]}
        for r in regions
        if r["layout_region_id"] in drop
    ]
    return FilterStageResult(
        [r for r in regions if r["layout_region_id"] not in drop],
        excluded,
        {"drop_count": len(excluded)},
    )
