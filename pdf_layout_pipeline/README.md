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
