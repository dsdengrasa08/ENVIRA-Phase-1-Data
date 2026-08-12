"""Layout overlays returned as displayable RGB images."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from .geometry import int_bbox


@dataclass
class Overlay:
    page_number: int
    image: np.ndarray
    path: Path | None = None


_COLORS = {
    "Text": (0, 180, 0),
    "Title": (255, 0, 255),
    "Section-header": (200, 0, 200),
    "List": (255, 120, 0),
    "Table": (0, 140, 255),
    "Formula": (0, 255, 255),
    "Caption": (180, 0, 180),
    "Footnote": (120, 120, 0),
    "Reference": (80, 180, 80),
    "Page-header": (120, 120, 120),
    "Page-footer": (80, 80, 80),
    "Figure": (0, 0, 255),
    "Unknown": (180, 180, 180),
}


def _label(image, text, origin, color):
    import cv2

    cv2.putText(
        image, text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA
    )


def render_layout_overlay(page, output_path: Path | None = None) -> Overlay:
    import cv2

    image = cv2.imread(str(page["page_image_path"]), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(page["page_image_path"])
    for r in page.get("asset_aware_overlay_regions", page["layout_regions"]):
        x0, y0, x1, y1 = int_bbox(tuple(r["bbox_px"]))
        typ = r.get("type", "Unknown")
        color = _COLORS.get(typ, _COLORS["Unknown"])
        cv2.rectangle(image, (x0, y0), (x1, y1), color, 3)
        if r.get("asset_association_role"):
            prefix = f"A{r.get('asset_overlay_order', '?')}"
            label = f"{prefix} {typ}/{r['asset_association_role']} [post_body_asset]"
        else:
            label = f"{r.get('visual_overlay_order', '')} {typ}".strip()
        if r.get("synthetic_detection_method") == "caption_anchored_figure_completion":
            label += " [completed]"
        if r.get("resolution_action") == "semantic_caption_split":
            label += f" [split:{r.get('caption_object_type', '?')}]"
        _label(image, label, (x0 + 4, max(18, y0 + 18)), color)
    _label(
        image,
        f"Docling layout | page {page['page_number']} | article={len(page['layout_regions'])} | assets={len(page.get('post_body_asset_regions', []))}",
        (24, 36),
        (0, 0, 255),
    )
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_path), image)
    return Overlay(
        page["page_number"], cv2.cvtColor(image, cv2.COLOR_BGR2RGB), output_path
    )


def render_layout_overlays(run, save=True):
    """Render the consumer-facing resolved layout with one box per caption group."""
    return [
        render_layout_overlay(
            _page_with_regions(page, _semantic_display_regions(run, page)),
            (
                run.document.artifacts.overlay_dir
                / f"page_{page['page_number']:04d}_docling_layout_overlay.png"
                if save
                else None
            ),
        )
        for page in run.pages
    ]


def _page_with_regions(page, regions, key="layout_regions"):
    page_number = int(page["page_number"])
    value = dict(page)
    value[key] = [r for r in regions if int(r["page_number"]) == page_number]
    value.pop("asset_aware_overlay_regions", None)
    return value


def _semantic_display_regions(run, page):
    """Return resolved regions with caption members replaced by one logical box."""
    page_number = int(page["page_number"])
    groups = [
        group
        for group in run.caption_groups
        if int(group["page_number"]) == page_number
    ]
    grouped_ids = {
        str(region_id)
        for group in groups
        for region_id in group["ordered_source_region_ids"]
    }
    regions = [
        dict(region)
        for region in run.resolved_regions
        if int(region["page_number"]) == page_number
        and str(region["layout_region_id"]) not in grouped_ids
        and region.get("emission_policy")
        not in {"suppress_duplicate_text_emission", "emit_as_nested_child"}
    ]
    by_id = {str(region["layout_region_id"]): region for region in run.resolved_regions}
    for group in groups:
        members = [
            by_id[str(region_id)]
            for region_id in group["ordered_source_region_ids"]
            if str(region_id) in by_id
        ]
        if not members:
            continue
        boxes = [list(map(float, member["bbox_px"])) for member in members]
        regions.append(
            {
                "layout_region_id": group["resolved_region_id"],
                "page_number": page_number,
                "type": "Caption",
                "text": group.get("text", ""),
                "bbox_px": [
                    min(box[0] for box in boxes),
                    min(box[1] for box in boxes),
                    max(box[2] for box in boxes),
                    max(box[3] for box in boxes),
                ],
                "visual_overlay_order": min(
                    int(member.get("resolved_reading_order") or 10**9)
                    for member in members
                ),
                "source_region_ids": group["source_region_ids"],
                "resolution_action": "semantic_caption_group",
            }
        )
    return sorted(
        regions,
        key=lambda region: (
            int(region.get("visual_overlay_order") or 10**9),
            float(region["bbox_px"][1]),
            float(region["bbox_px"][0]),
        ),
    )


def render_raw_detection_overlays(run, save=True):
    """Render immutable Docling regions separately from filtered semantics."""
    return [
        render_layout_overlay(
            _page_with_regions(page, run.raw_regions),
            (
                run.document.artifacts.overlay_dir
                / f"page_{page['page_number']:04d}_raw_layout_overlay.png"
                if save
                else None
            ),
        )
        for page in run.pages
    ]


def render_resolved_layout_overlays(run, save=True):
    """Render duplicate-resolved regions while retaining source IDs in labels."""
    return [
        render_layout_overlay(
            _page_with_regions(page, run.resolved_regions),
            (
                run.document.artifacts.overlay_dir
                / f"page_{page['page_number']:04d}_resolved_layout_overlay.png"
                if save
                else None
            ),
        )
        for page in run.pages
    ]


def render_table_context_overlay(run, page_number, output_path: Path | None = None):
    """Render every logical table while leaving the raw layout overlay available."""
    import cv2

    page = next(page for page in run.pages if page["page_number"] == page_number)
    image = cv2.imread(str(page["page_image_path"]), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(page["page_image_path"])
    regions = {r["layout_region_id"]: r for r in run.final_regions}
    palette = [(0, 140, 255), (220, 80, 20), (40, 170, 80), (180, 60, 180)]
    role_specs = {
        "Body": (4, cv2.LINE_8),
        "Identifier": (2, cv2.LINE_AA),
        "Caption": (2, cv2.LINE_AA),
        "Note": (1, cv2.LINE_AA),
    }
    for index, group in enumerate(
        (g for g in run.logical_tables if g["page_number"] == page_number), 1
    ):
        color = palette[(index - 1) % len(palette)]
        roles = {
            "Body": [group["table_region_id"]],
            "Identifier": group["identifier_region_ids"],
            "Caption": group["caption_region_ids"],
            "Note": group["note_region_ids"],
        }
        for role, region_ids in roles.items():
            thickness, line_type = role_specs[role]
            for fragment, region_id in enumerate(region_ids, 1):
                region = regions.get(region_id)
                if not region:
                    continue
                x0, y0, x1, y1 = int_bbox(tuple(region["bbox_px"]))
                cv2.rectangle(image, (x0, y0), (x1, y1), color, thickness, line_type)
                suffix = f" {fragment}" if len(region_ids) > 1 else ""
                _label(
                    image,
                    f"T{index:02d} / {role}{suffix}",
                    (x0 + 4, max(18, y0 + 18)),
                    color,
                )
    _label(image, f"Logical table context | page {page_number}", (24, 36), (0, 0, 255))
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_path), image)
    return Overlay(page_number, cv2.cvtColor(image, cv2.COLOR_BGR2RGB), output_path)


def render_caption_overlap_overlay(run, page_number, output_path: Path | None = None):
    """Render semantic caption groups and compact overlap relationship labels."""
    import cv2

    page = next(page for page in run.pages if page["page_number"] == page_number)
    image = cv2.imread(str(page["page_image_path"]), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(page["page_image_path"])
    regions = {str(r["layout_region_id"]): r for r in run.resolved_regions}
    palette = [(180, 60, 180), (30, 150, 230), (40, 170, 80), (220, 80, 20)]
    abbreviations = {
        "DUPLICATE": "DUP",
        "NESTED_COMPONENT": "NEST",
        "COMPLEMENTARY_FRAGMENT": "FRAG",
        "CROSS_ROLE_BOUNDARY_OVERLAP": "BOUND",
        "AMBIGUOUS": "AMB",
    }
    groups = [g for g in run.caption_groups if g["page_number"] == page_number]
    for index, group in enumerate(groups, 1):
        color = palette[(index - 1) % len(palette)]
        for fragment, region_id in enumerate(group["ordered_source_region_ids"], 1):
            region = regions.get(region_id)
            if not region:
                continue
            x0, y0, x1, y1 = int_bbox(tuple(region["bbox_px"]))
            thickness = 2 if region_id in group["identifier_region_ids"] else 1
            cv2.rectangle(image, (x0, y0), (x1, y1), color, thickness, cv2.LINE_AA)
            _label(
                image, f"T{index:02d}/C{fragment}", (x0 + 4, max(18, y0 + 18)), color
            )
        for relation in group["relationships"]:
            left = regions.get(relation["left_region_id"])
            right = regions.get(relation["right_region_id"])
            if not left or not right:
                continue
            x = int(
                (
                    max(left["bbox_px"][0], right["bbox_px"][0])
                    + min(left["bbox_px"][2], right["bbox_px"][2])
                )
                / 2
            )
            y = int(max(left["bbox_px"][1], right["bbox_px"][1]))
            _label(
                image,
                abbreviations.get(relation["kind"], relation["kind"]),
                (x, max(18, y)),
                color,
            )
    _label(
        image,
        f"Resolved caption relationships | page {page_number}",
        (24, 36),
        (0, 0, 255),
    )
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_path), image)
    return Overlay(page_number, cv2.cvtColor(image, cv2.COLOR_BGR2RGB), output_path)


def render_overlap_resolution_overlay(
    run, page_number, output_path: Path | None = None
):
    """Render original/resolved/suppressed geometry and unresolved graph edges."""
    import cv2

    page = next(page for page in run.pages if page["page_number"] == page_number)
    image = cv2.imread(str(page["page_image_path"]), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(page["page_image_path"])
    resolved = {
        str(region["layout_region_id"]): region
        for region in run.resolved_regions
        if int(region["page_number"]) == page_number
    }
    suppressed = {
        str(region["layout_region_id"]): region
        for region in run.suppressed_regions
        if int(region["page_number"]) == page_number
    }
    # Thin gray source geometry remains visible beneath the resolved view.
    for region in resolved.values():
        source = region.get("source_bbox_px", region["bbox_px"])
        x0, y0, x1, y1 = int_bbox(tuple(source))
        cv2.rectangle(image, (x0, y0), (x1, y1), (150, 150, 150), 1, cv2.LINE_AA)
    for region in resolved.values():
        x0, y0, x1, y1 = int_bbox(
            tuple(region.get("resolved_bbox_px", region["bbox_px"]))
        )
        color = (
            (0, 165, 255)
            if region.get("resolution_status") == "ambiguous"
            else (40, 180, 40)
        )
        cv2.rectangle(image, (x0, y0), (x1, y1), color, 2, cv2.LINE_AA)
        _label(
            image, str(region["layout_region_id"]), (x0 + 3, max(18, y0 + 16)), color
        )
    for region in suppressed.values():
        x0, y0, x1, y1 = int_bbox(tuple(region["bbox_px"]))
        cv2.rectangle(image, (x0, y0), (x1, y1), (80, 80, 220), 1, cv2.LINE_4)
        cv2.line(image, (x0, y0), (x1, y1), (80, 80, 220), 1)
    for relationship in run.layout_relationships:
        if relationship["page_number"] != page_number:
            continue
        parent = resolved.get(str(relationship.get("parent_region_id")))
        child = resolved.get(str(relationship.get("child_region_id")))
        if parent and child:
            pb, cb = parent["bbox_px"], child["bbox_px"]
            p = (int((pb[0] + pb[2]) / 2), int((pb[1] + pb[3]) / 2))
            c = (int((cb[0] + cb[2]) / 2), int((cb[1] + cb[3]) / 2))
            cv2.arrowedLine(image, p, c, (220, 120, 20), 1, cv2.LINE_AA, tipLength=0.08)
    _label(image, f"Overlap resolution | page {page_number}", (24, 36), (0, 0, 255))
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_path), image)
    return Overlay(page_number, cv2.cvtColor(image, cv2.COLOR_BGR2RGB), output_path)
