# Contributing

## Development setup

Create an isolated Python 3.10–3.13 environment and install both projects:

```bash
python -m pip install -e './packages/envira_pdf_layout[dev]' -e './apps/envira_gradio[test]'
pre-commit install
```

Run `ruff check .`, `ruff format --check .`, `mypy packages/envira_pdf_layout/src apps/envira_gradio/src`, and both pytest suites before proposing a change.

## Change discipline

Keep pure moves, compatibility migrations, dependency updates, and algorithmic changes in separate commits. Algorithm changes require a regression fixture, a scientific rationale, and comparison of region identities, geometry, reading order, relationships, schemas, and representative overlays. Do not commit private PDFs, extracted private text, model binaries, secrets, or generated run directories.

Use conventional, descriptive `snake_case` Python names and type all new public APIs. Catch broad exceptions only at process or user-interface boundaries. New behavior must be documented and tested.
