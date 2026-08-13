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
# From this directory:
python -m pip install -e ".[notebook]"
export PHASE1_USE_GOOGLE_DRIVE=0
export PHASE1_PROJECT_DIR=/persistent/envira/phase1_docling
jupyter lab pdf_layout_pipeline_workflow.ipynb
```

From the repository root, use
`python -m pip install -e "./pdf_layout_pipeline-AEE-vWiP[notebook]"` instead.
Legacy and Colab callers may continue using the path-independent
`python -m pip install -r pdf_layout_pipeline-AEE-vWiP/requirements.txt` command.

The installed application also provides a notebook-independent CLI:

```bash
envira-pdf-layout config --effective --config config/default.yaml
envira-pdf-layout run input.pdf --output-dir ./runs --config config/default.yaml
envira-pdf-layout validate ./runs/outputs/docling_layout_only/DOCUMENT_ID
envira-pdf-layout compare baseline.jsonl candidate.jsonl
```

CLI output is JSON. Exit codes are `0` for complete results, `2` for invalid
configuration, `3` for invalid input, `4` for unavailable dependencies, `5` for
an exported partial result, `6` for pipeline failure, and `7` for invalid artifacts.
Existing terminal runs are refused by default. `--overwrite` starts a new attempt;
`--resume` only reuses an artifact set whose source hash, effective-config hash, and
manifest validation match. Export removes stale terminal markers before publication,
uses `_EXPORTING` while files are replaced atomically, and writes exactly one terminal
marker last so consumers never treat an in-progress publication as complete.
Security limits, private file modes, secret redaction, raw-content controls, and the
untrusted-input deployment model are documented in [`SECURITY.md`](SECURITY.md).
Dependency locking, clean-wheel verification, model manifests, SBOMs, and runtime
fingerprints are documented in [`SUPPLY_CHAIN.md`](SUPPLY_CHAIN.md).

The Docling converter is initialized once. The workflow then renders pages,
converts the full selected range, processes layout regions, visibly renders the
asset-aware overlays, and exports JSON, JSONL, Markdown, CSV, and PNG artifacts.

## Package map

- `config.py`: immutable grouped run configuration and environment parsing.
- `runtime.py`, `paths.py`, `model_artifacts.py`: runtime, identity, persistence,
  and model setup.
- `pdf_io.py`, `docling_backend.py`: input and backend boundary.
- `independent_core.py`: small implementation dispatcher and shadow-comparison boundary.
- `preserved_core.py`: frozen compatibility extraction of the remaining established
  stages; it is serialized and explicitly capability-limited while stages migrate to
  immutable contracts. See [`CORE_MIGRATION.md`](CORE_MIGRATION.md).
- `authoritative.py`: compatibility alias for callers using the former entry point;
  it delegates directly to the independent package core and does not load a
  notebook.
- `region_conversion.py`: the active Docling-to-ENVIRA conversion boundary. It
  supports object and serialized Docling documents, preserves production IDs and
  fields, and reports skipped provenance explicitly.
- `filtering/`, `assets/`, `reading_order.py`: smaller independently testable
  compatibility helpers. Until each is migrated under equivalence tests, the
  corresponding established compatibility heuristic remains in `preserved_core.py`.
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
- `roi_ocr.py`: cached, ROI-only OCR with source-coordinate mapping, guaranteed
  resource cleanup, geometry validation, categorized contextual failures, and a
  dependency-only circuit breaker. Page-local OCR failures remain isolated and do
  not prevent fallback attempts on later pages.
- `stage_trace.py`: compact stage-by-stage region counts, ID deltas, relationship
  counts, and invariants for locating the first stage that introduced a regression.
- `region_index.py`: immutable per-collection page, ID, type, page-size, and
  normalized-text indexes shared by hierarchy, caption, and table-context stages.
- `schema.py`: versioned region/relationship contracts, coordinate metadata,
  geometry lifecycle updates, validation, and additive legacy migration. See
  [`SCHEMA.md`](SCHEMA.md) and the machine-readable contracts under `schemas/`.

Geometry-heavy stages publish deterministic work counters alongside elapsed time.
Overlap observations are reused by hierarchy policy, and the shared region index
prevents repeated page/type/text indexing without introducing a mutable global cache.

## Regression contracts

Fast synthetic regression fixtures live under `tests/fixtures/regression` and use
versioned semantic expectations rather than pixel-perfect screenshots. Stage traces
carry a schema version and can be compared with
`python -m envira_pdf_layout.regression compare BASELINE CANDIDATE`. Golden updates
require an explicit fixture and reason and refuse invalid traces by default. Use
`constraints-regression.txt` for reproducible model-backed or scheduled corpus runs;
the default pull-request suite remains model-free. Export validation checks required
artifacts, hierarchy partitions, relationship endpoints, unresolved containment,
and trace schema compatibility.
Region exports additionally preserve immutable source geometry, distinguish
physical, visual-crop, and semantic-group boxes, and record every accepted or
rejected proposal in versioned geometry history.

Test tiers are registered in `pytest.ini`: run `pytest -m regression` for the
generated semantic fixtures, `pytest -m performance` for deterministic work
contracts, and reserve `pytest -m model` for scheduled/model-backed environments.
Committed fixtures are repository-generated JSON contracts and contain no
third-party PDF content; private evaluation PDFs should remain in private CI jobs.

## Failure policy and partial results

`error_policy` selects `strict` or `report` behavior for package-owned stages.
Strict mode raises a structured `PipelineStageError`; report mode records a
`PipelineIssue`, marks the run partial, and uses only declared conservative
fallbacks (retain core regions, retain all hierarchy regions at top level, or
leave captions unattached). Results expose status, failed pages/stages, completed
stages, and issues. Exports use atomic per-file replacement, emit page diagnostics
and a hashed manifest, and finish with exactly one `_SUCCESS`, `_PARTIAL`, or
`_FAILED` marker so an incomplete directory cannot masquerade as a successful run.
`retry.build_retry_plan` reads page diagnostics and permits selective retry only
when the source PDF hash and effective configuration match the prior run.

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
All ownership thresholds live in the typed `caption_association` configuration
section and the effective values are captured with the run configuration.

## Logical table context

After the core filters and reading-order assignment, the package creates
one logical group for every retained table. Groups reference existing region IDs;
they do not reclassify regions or enlarge the physical table-body bounding box.
Association combines normalized geometry, column compatibility, reading order,
generic lexical and optional typography evidence, structural stopping boundaries,
and exclusive candidate ownership. Results are available in
`PipelineResult.logical_tables`, each page's `logical_tables` field, diagnostics,
the optional table-context overlay, and `logical_tables.jsonl`.

Every run also exports `stage_trace.jsonl`. The trace records compact counts by
page and class, added/removed region IDs, relationship and decision counts, and
geometry/type changes, stable content digests, elapsed time, and
geometry/identity/hierarchy invariants after each major stage. The notebook
displays this trace directly, making the earliest divergent stage visible without
diffing full region payloads or rerunning OCR and model inference.

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
