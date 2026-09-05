"""Preserve scientific assets after the main-body boundary."""

from __future__ import annotations
import re


def collect_post_body_assets(excluded_regions):
    asset_regions = []
    records = []
    assets = [r for r in excluded_regions if r["type"] in {"Figure", "Table"}]
    for order, asset in enumerate(assets, 1):
        number_match = re.search(
            r"\b(?:fig(?:ure)?|table)\s*(\d+)\b", asset.get("text", ""), re.I
        )
        linked = [
            r
            for r in excluded_regions
            if r["page_number"] == asset["page_number"]
            and r["type"] in {"Caption", "Footnote", "Text"}
            and abs(r["bbox_px"][1] - asset["bbox_px"][3]) < 120
        ]
        asset_copy = {
            **asset,
            "asset_overlay_order": order,
            "asset_association_role": "asset",
            "document_scope": "post_body_asset",
        }
        asset_regions.append(asset_copy)
        asset_regions.extend(
            {
                **r,
                "asset_overlay_order": order,
                "asset_association_role": "caption_or_note",
                "document_scope": "post_body_asset",
            }
            for r in linked
        )
        records.append(
            {
                "asset_id": asset["layout_region_id"],
                "page_number": asset["page_number"],
                "type": asset["type"],
                "number": number_match.group(1) if number_match else None,
                "region_ids": [
                    asset["layout_region_id"],
                    *[r["layout_region_id"] for r in linked],
                ],
            }
        )
    return records, asset_regions
