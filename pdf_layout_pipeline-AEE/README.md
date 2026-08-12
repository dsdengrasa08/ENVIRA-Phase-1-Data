# ENVIRA modular PDF layout pipeline

This directory is the maintained, package-backed successor to the repository-root
`pdf_layoutparser_vF.ipynb`. The root notebook remains an unchanged reference
implementation. The new workflow preserves its visible, stage-by-stage inspection
style while moving reusable processing into `src/envira_pdf_layout`.

## Run

### Colab

Open `pdf_layout_pipeline_workflow.ipynb`, set `SOURCE_PDF`, run the optional
installation cell, and execute top to bottom. Google Drive and model paths retain
the `PHASE1_*` environment-variable overrides used by the reference notebook.

### Local/server

```bash
python -m pip install -r requirements.txt
export PYTHONPATH="$PWD/src"
export PHASE1_USE_GOOGLE_DRIVE=0
export PHASE1_PROJECT_DIR=/persistent/envira/phase1_docling
jupyter lab pdf_layout_pipeline_workflow.ipynb
```

The Docling converter is initialized once. The workflow then renders pages,
converts the full selected range, processes layout regions, visibly renders the
asset-aware overlays, and exports JSON, JSONL, Markdown, CSV, and PNG artifacts.

## Package map

- `config.py`: immutable grouped run configuration and environment parsing.
- `runtime.py`, `paths.py`, `model_artifacts.py`: runtime, identity, persistence,
  and model setup.
- `pdf_io.py`, `docling_backend.py`: input and backend boundary.
- `authoritative.py`: fidelity adapter that executes the immutable reference
  notebook's item conversion, page-1 recovery, filters, asset recovery, and
  reading-order implementation in an isolated namespace.
- `filtering/`, `assets/`, `region_conversion.py`, `reading_order.py`: legacy
  independently testable helpers retained for compatibility; the maintained
  workflow does not substitute them for the authoritative algorithms.
- `visualization.py`, `diagnostics.py`, `results.py`: visible notebook outputs.
- `export.py`: serialization only.
- `pipeline.py`: high-level stage orchestration.
- `table_context.py`: publisher-independent logical association of each retained
  table body with optional identifier, caption, note, footnote, and source regions.
- `caption_overlap.py`: conservative caption-overlap analysis, clear-duplicate
  resolution, and provenance-preserving semantic caption groups.
- `caption_validation.py`: line-level semantic-spatial validation of detector
  captions, conservative one-to-many segmentation, and reassociation.
- `layout_overlap.py`: generalized class-family relationship graph, immutable
  source/resolved geometry, complete-link duplicate canonicalization,
  hierarchy/conflict/fragment analysis, and attachable-parent association.

## Generalized overlap resolution

The maintained pipeline now resolves overlaps after the authoritative filters and
before semantic context grouping. Regions removed by the authoritative nested-
asset filter are conservatively restored to the relationship layer as nested
children, so their text and geometry remain auditable without forcing them into
the top-level reading stream.

Resolution is deliberately split into observation, classification, and action:

1. page-local sweep-line candidate generation;
2. directional geometry, text, class-family, and alignment features;
3. duplicate, containment, class-conflict, accidental-intersection,
   fragmentation, invalid-occlusion, and ambiguity relationships;
4. complete-link duplicate canonicalization (preventing transitive drift);
5. parent-local ordering for nested children and final top-level order;
6. non-destructive caption association to tables, figures, equations/formulas,
   and future attachable asset classes.

Every resolved region retains `source_bbox_px`, `resolved_bbox_px`,
`source_region_ids`, an emission policy, and resolution status. Generalized
relationships, action decisions, and suppressed source detections are exported
as separate JSONL artifacts. The workflow provides a resolution overlay showing
source geometry, resolved geometry, suppressed detections, hierarchy arrows, and
unresolved conflicts.

## Logical table context

After the authoritative filters and reading-order assignment, the package creates
one logical group for every retained table. Groups reference existing region IDs;
they do not reclassify regions or enlarge the physical table-body bounding box.
Association combines normalized geometry, column compatibility, reading order,
generic lexical and optional typography evidence, structural stopping boundaries,
and exclusive candidate ownership. Results are available in
`PipelineResult.logical_tables`, each page's `logical_tables` field, diagnostics,
the optional table-context overlay, and `logical_tables.jsonl`.

Caption association is seed anchored: a detector `Caption` region or a generalized
table-label prefix first establishes a caption-to-table candidate. Once that
association is unambiguous, every horizontally compatible text region physically
between the caption and table is included in the caption, regardless of whether
its wording resembles a body paragraph. This corridor rule handles the common
case where only a short `Table N.` label is classified as a caption and its full
description is classified as ordinary text. Competing table corridors remain
unassigned rather than being guessed.

Outside the caption-to-table corridor, a conservative local graph grows across
aligned, line-adjacent `Text`/`Caption` fragments in reading order. Edge scoring
combines page- and line-relative gaps, horizontal overlap, left/right alignment,
column compatibility, detector class, optional typography, lexical continuity,
and relationships from generalized overlap resolution. Structural blockers,
paragraph-like prose, competing table assignments, new object prefixes, and
unresolved overlap conflicts prevent or penalize this out-of-corridor growth.

Printed labels such as ordinary, supplementary, extended-data, Roman-numeral, and
appendix table identifiers are metadata. Stable internal IDs do not depend on OCR
success or the presence of a printed number. Cross-page continuation fields are
reserved on each page-local group for a later document-level continuation stage.

## Caption overlap resolution

Before caption-to-object association, merged-caption validation reuses native PDF
lines or structured `text_lines`/`ocr_lines`; integrations may supply a structured
OCR provider as a selective fallback. Prefixes at logical line starts only propose
boundaries. A split is accepted only when every segment has a distinct,
type-compatible nearby parent and the joint semantic-spatial score beats the
unsplit hypothesis by a configured margin. Accepted segments preserve their source
detector ID and box; ambiguous regions remain unchanged with auditable evidence.

This prevents descriptive cross-references such as “Figure 3 ... reported in Table
2” from being split merely because another object identifier occurs in the text.
If native extraction omits a small styled leading identifier, the first segment may
still be inferred from a distinct, type-compatible neighboring object, but only
when a later explicit caption anchor has its own different parent. Resolved overlays
mark derived boxes as `[split:Figure]`, `[split:Table]`, and so on; raw overlays
intentionally continue to show the immutable merged Docling detection.

Overlap handling is deliberately separate from physical layout filtering. Despite
the compatibility module name, intersecting regions of every semantic class are
analyzed; caption and table relationships receive additional role-aware grouping.
The pipeline preserves `raw_regions` and authoritative `final_regions`, then creates
`resolved_regions` by collapsing only near-identical, role-compatible detections
with compatible text evidence. Nested identifiers, complementary caption fragments,
caption/table boundary overlaps, and ambiguous pairs remain available. Pairwise
geometry includes IoU, directional containment, intersection over the smaller
region, horizontal/vertical overlap, relative area, token coverage/Jaccard,
normalized center distance, and normalized edge deltas. Slight asset/text boundary
contacts are distinguished from substantial cross-role overlaps. Directional
containment records explicit parent and child IDs, and unique aligned text takes
precedence over a geometric nesting label.

Duplicate edges are resolved as connected components so three-way and chained
detections select one deterministic canonical item. Resolved regions retain source
IDs, an emission policy for canonical versus nested-child content, and a contiguous
resolved reading order; raw and authoritative reading order remain unchanged.

Table-context association runs on the conservatively resolved regions. A subsequent
context-aware pass creates `caption_groups`, preserving identifier and fragment
roles, source IDs, relationship evidence, ambiguity status, and parent table IDs.
Each group also exposes one deduplicated `text` value and the minimal
`semantic_text_region_ids` needed to produce it; contained identifier/line boxes
remain in `ordered_source_region_ids` for geometry and provenance but are not read
again as separate captions.
The consumer-facing group is typed as `Table Caption`, carries the union bbox, and
contains ordered child descriptors with derived identifier/fragment roles, source
types, source boxes, and detector scores. Source detections are not reclassified or
resized.
The physical table bbox is never resized. Outputs include raw, authoritative,
resolved, relationship, caption-group, and logical-table JSONL artifacts. Raw,
resolved, table-context, and caption-relationship visualization functions remain
separate so model and post-processing behavior can be inspected independently.

The workflow notebook is pinned to `pdf_layout_pipeline-AEE/src` and verifies the
imported package path at runtime, preventing a legacy sibling directory or a stale
Colab import from silently bypassing overlap resolution. Its primary overlay uses
the semantic resolved view, where all physical members of a caption group are
rendered as one union box; raw and physical resolved overlays remain available as
explicit diagnostics.

## Output compatibility and validation

The migration preserves stable document IDs, page-oriented records, normalized
region types, reading-order fields, filter reasons, separate main-body and
post-body streams, and asset-aware overlays. Before promoting a new detector
change, compare a fixed reference run against the original notebook for:

1. raw and final counts by page/type;
2. excluded region IDs and reasons by stage;
3. bounding boxes and reading-order assignments;
4. tail boundary and post-body associations;
5. serialized schemas and summary values;
6. overlay dimensions, labels, geometry, and representative visual diffs.

Algorithmic cleanup should be committed separately from output-equivalence work.
