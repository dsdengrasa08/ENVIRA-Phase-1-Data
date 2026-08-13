# Layout schema and geometry lifecycle

ENVIRA exports use an explicit, additive versioned contract. `region_schema_version`,
`relationship_schema_version`, `geometry_history_schema_version`, and proposal schema
versions evolve independently. Readers must reject unsupported future versions rather
than silently guessing their meaning. Legacy region dictionaries can be upgraded with
`migrate_region()`; stable region IDs are never rewritten.

## Geometry roles

- `source_bbox_px` is the immutable detector/converter observation.
- `proposed_bbox_px` is the latest candidate geometry and is never authoritative alone.
- `resolved_bbox_px` is the accepted physical geometry.
- `bbox_px` and `physical_bbox_px` are compatibility aliases of `resolved_bbox_px`.
- `visual_crop_bbox_px` controls rendering/cropping and may intentionally differ.
- `semantic_group_bbox_px` describes a logical group and must not overwrite physical geometry.

Coordinates use half-open `(x0, y0, x1, y1)` page-pixel boxes with a top-left origin.
Every region records page dimensions and render DPI when known. Width, height, and area
are derived fields maintained atomically with authoritative geometry changes.

## Geometry history

Each region begins at `geometry_version: 1` with a conversion event. Every proposal
appends an immutable history event containing source, proposed, resolved geometry,
stage, reason, and acceptance. An accepted geometry change increments the version;
rejected/no-op proposals are retained without incrementing it. Relationships record
the geometry version used to compute their features.

## Reading and grouping order

`layout_reading_order` is the authoritative document reading sequence.
`visual_overlay_order` is presentation-only. Nested children and captions preserve
their own stable IDs; semantic grouping is represented through relationships rather
than by replacing their physical boxes.

Machine-readable v1 contracts live in `schemas/`. Export validation checks region,
relationship, proposal, partition, manifest, and stage-trace versions before a run is
accepted as consumable.
