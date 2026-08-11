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
            prefix = f"A{r.get('asset_overlay_order','?')}"
            label = f"{prefix} {typ}/{r['asset_association_role']} [post_body_asset]"
        else:
            label = f"{r.get('visual_overlay_order','')} {typ}".strip()
        if r.get("synthetic_detection_method") == "caption_anchored_figure_completion":
            label += " [completed]"
        _label(image, label, (x0 + 4, max(18, y0 + 18)), color)
    _label(
        image,
        f"Docling layout | page {page['page_number']} | article={len(page['layout_regions'])} | assets={len(page.get('post_body_asset_regions',[]))}",
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
    return [
        render_layout_overlay(
            page,
            (
                run.document.artifacts.overlay_dir
                / f"page_{page['page_number']:04d}_docling_layout_overlay.png"
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
