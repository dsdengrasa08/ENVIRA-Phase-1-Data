# ENVIRA modular PDF layout pipeline

This directory is the maintained, self-contained PDF layout pipeline. The workflow
preserves visible, stage-by-stage inspection while the complete active processing
implementation and its tests live inside this directory. No file outside this
directory is required to import, test, or run the pipeline.

## Run

### Colab

Open `pdf_layout_pipeline_workflow.ipynb`, set `SOURCE_PDF`, select the YAML
configuration profile, run the optional installation cell, and execute top to bottom. Google Drive and model paths support
the documented `PHASE1_*` environment-variable overrides.

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
- `independent_core.py`: package-owned orchestration of the remaining established
  page-1 recovery, filters, asset recovery, reading order, and output construction.
  Its preserved stage ordering remains the production implementation while stages
  are migrated incrementally under equivalence tests.
- `authoritative.py`: compatibility alias for callers using the former entry point;
  it delegates directly to the independent package core and does not load a
  notebook.
- `region_conversion.py`: the active Docling-to-ENVIRA conversion boundary. It
  supports object and serialized Docling documents, preserves production IDs and
  fields, and reports skipped provenance explicitly.
- `filtering/`, `assets/`, `reading_order.py`: smaller independently testable
  compatibility helpers. Until each is migrated under equivalence tests, the
  corresponding established production heuristic remains in `independent_core.py`.
- `visualization.py`, `diagnostics.py`, `results.py`: visible notebook outputs.
- `export.py`: serialization only.
- `pipeline.py`: high-level stage orchestration.
- `table_context.py`: publisher-independent logical association of each retained
  table body with optional identifier, caption, note, footnote, and source regions.
- `caption_overlap.py`: conservative caption-overlap analysis, clear-duplicate
  resolution, and provenance-preserving semantic caption groups.
- `layout_overlap.py`: generalized class-family relationship graph, immutable
  source/resolved geometry, complete-link duplicate canonicalization,
  hierarchy/conflict/fragment analysis, and attachable-parent association.
- `caption_association.py`: authoritative, class-aware and non-destructive
  caption ownership with explicit ambiguity and unattached outcomes.

## Generalized overlap resolution

The maintained pipeline resolves overlaps after the preserved core filters and
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

Nested asset handling is non-destructive. Figure/table containment is proposed in
the core, then validated once after duplicate resolution. Only semantically
compatible children with one unambiguous container receive nested emission;
expanded figures that newly capture text, nested containers, and competing parents
remain top-level conflicts. Reading order is assigned after hierarchy acceptance as
separate contiguous top-level and parent-local sequences. Explicit exports are
`physical_layout_regions.jsonl`, `top_level_layout_regions.jsonl`, and
`nested_layout_regions.jsonl`; `final_regions` remains a compatibility name for the
core-filtered physical input.

General overlap resolution treats containment as observation only and emits
`CONTAINMENT_CANDIDATE`; it never changes hierarchy emission. The hierarchy stage
uses the shared typed containment thresholds, an explicit parent/child compatibility
matrix, and explainable child-role inference. Text containment is classified as a
duplicate, identifier fragment, or ambiguous text occlusion rather than container
hierarchy. Unknown and incompatible combinations remain top-level, including a
non-container covering only one child. Exactly one authoritative containment outcome
per pair replaces the observational candidate in exported relationships.

Caption-anchored figure completion is likewise proposal-based. The preserved image
detector proposes geometry, then `figure_completion.py` validates caption confidence,
growth, page bounds, newly captured regions, structural barriers, competing assets,
and column-gutter crossings before downstream filtering. Rejected and ambiguous
proposals restore detector geometry. Every proposal preserves source, proposed,
resolved, visual-crop, and semantic-group boxes plus deterministic geometry history.
Proposal records are exported to `figure_completion_proposals.jsonl` and displayed
with a source/proposal/barrier overlay in the workflow notebook.

Caption ownership is resolved by one non-destructive, class-aware association
stage. Explicit `Figure`, `Table`, `Equation`, `Algorithm`, and `Listing`
identifiers constrain eligible parent classes; detector-only captions use the same
geometry, column, direction, blocker, and ambiguity checks. Every candidate emits
an associated, unresolved, or unattached relationship, and no caption association
resizes, reclassifies, suppresses, or silently selects a parent by input order.

## Logical table context

After the core filters and reading-order assignment, the package creates
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

Overlap handling is deliberately separate from physical layout filtering. Despite
the compatibility module name, intersecting regions of every semantic class are
analyzed; caption and table relationships receive additional role-aware grouping.
The pipeline preserves `raw_regions` and core `final_regions`, then creates
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

## Configuration precedence

`PipelineConfig.load()` is the authoritative loader. Values are merged in the
following order: typed defaults, the selected YAML profile, `PHASE1_*` environment
variables, and explicit notebook/CLI overrides. Unknown YAML sections and fields are
rejected. The complete effective configuration, its profile path, value provenance,
and the captured legacy-core environment are written to `effective_config.json`.
`PipelineConfig.from_env()` remains a compatibility wrapper around the same loader.
The preserved core executes against the captured configuration snapshot with ambient
`PHASE1_*` variables isolated for reproducible runs.

## Generalized heuristic policy

Publisher vocabulary is stored in named data profiles rather than embedded in
destructive filter conditions. The default `confirmatory` mode requires publisher
lexical evidence to agree with generic page geometry and title/body structure;
`evidence_only` records matches without changing output. A conservative document-
family classifier reports its signals and falls back to `unknown`. Evidence,
document-family signals, and content-policy decisions are exported in
`pipeline_diagnostics.json`. Consumer choices
for references, acknowledgements, declarations, appendices, supplementary sections,
and front matter are configured separately from layout-noise correction. See
`HEURISTICS.md` for the active destructive-rule inventory and safeguards.
