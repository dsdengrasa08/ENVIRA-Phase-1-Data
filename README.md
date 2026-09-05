# ENVIRA PDF Layout

ENVIRA is an auditable research-software pipeline for extracting semantic layout regions from PDF documents. This repository contains one canonical Python library and a Gradio application that consumes it.

## Project status

> **Research software under active development.** This repository is not yet a
> stable production release; interfaces, configuration, and generated artifacts may
> change as the system is evaluated and refined.

### Model provenance and planned release

The fine-tuned model used in this repository was developed for the **EMNLP
Workshop submission**. The **EACL 2027 System Demonstrations submission** uses
that same fine-tuned model as part of its demonstrated system.

The fine-tuned model is not yet available as a stable public dependency. We plan
to release access to it in a future API and/or reusable software library; the
release format, interface, licensing terms, and availability will be documented
when they are finalized. Until then, this repository should be treated as the
research implementation rather than as a public model service.

These statements describe submissions and do not imply acceptance or endorsement
by either venue. For reproducibility, results reported in the submissions should
be associated with the exact Git commit, configuration, dependency constraints,
and model manifest used for the corresponding experiment.

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
