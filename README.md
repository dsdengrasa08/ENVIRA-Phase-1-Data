# ENVIRA PDF Layout

ENVIRA is an auditable research-software pipeline for extracting semantic layout regions from PDF documents. This repository contains one canonical Python library and a Gradio application that consumes it.

## Components

| Component | Purpose |
| --- | --- |
| [`packages/envira_pdf_layout`](packages/envira_pdf_layout) | Canonical pipeline library and `envira-pdf-layout` CLI |
| [`apps/envira_gradio`](apps/envira_gradio) | Thin Gradio user interface built on the canonical library |
| [`notebooks`](notebooks) | Colab-oriented workflow and application launchers |
| [`docs`](docs) | Architecture, methodology, operations, and reproducibility guidance |

## Quick start

Python 3.10–3.13 is supported.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e './packages/envira_pdf_layout[dev]'
envira-pdf-layout doctor --config packages/envira_pdf_layout/config/default.yaml
envira-pdf-layout run input.pdf --output-dir ./runs \
  --config packages/envira_pdf_layout/config/default.yaml
```

To develop the web application:

```bash
python -m pip install -e './packages/envira_pdf_layout[dev]' -e './apps/envira_gradio[test]'
pytest -q packages/envira_pdf_layout/tests apps/envira_gradio/tests
```

## Data, models, and outputs

Input PDFs are untrusted and may contain sensitive material. Do not commit private corpora, downloaded models, or generated runs. See [`data/README.md`](data/README.md), [`models/README.md`](models/README.md), and [`results/README.md`](results/README.md). Model identity, input hashes, effective configuration, dependencies, and schema versions should be retained for every published experiment.

## Reproducibility and documentation

- [Reproducing an experiment](docs/reproducibility/experiments.md)
- [Data requirements](docs/reproducibility/data.md)
- [Model requirements](docs/reproducibility/models.md)
- [Architecture](docs/architecture/overview.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)

## Citation and license

Please cite the software using [`CITATION.cff`](CITATION.cff). The project is released under the [BSD 3-Clause License](LICENSE).
