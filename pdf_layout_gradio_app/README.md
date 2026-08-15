# ENVIRA PDF Layout Gradio App

A standalone Gradio interface around the maintained ENVIRA/Docling PDF layout pipeline. The application accepts one local PDF, saves the complete processing artifact set to Google Drive (or another explicitly mounted persistent root), and displays only the final semantic page overlays.

This directory contains its own pipeline implementation, configuration, schemas, packaging metadata, UI, launcher, and tests. It neither imports from nor requires `pdf_layout_pipeline-AEE-vWiP` at runtime.

## Primary Colab workflow

1. Place this folder in the Colab filesystem or clone the repository.
2. Open `run_gradio_web_app.ipynb`.
3. Run the cells from top to bottom.
4. Authorize the Google Drive mount when prompted.
5. Upload a PDF in the launched Gradio application.

The notebook is deliberately a launcher. Core processing is implemented in the Python modules under `src/`.
The installation cell uses the active notebook kernel's Python executable and explicitly registers the standalone `src/` directory, so the following import cells work without a kernel restart.
The launch cell is non-blocking and requests a normal Gradio share link. If Gradio's share service is unavailable, it automatically embeds a Google Colab kernel-proxy URL instead of leaving only an inaccessible `localhost` link.

## Persistent output

The default Colab output root is:

```text
/content/drive/MyDrive/ENVIRA/pdf-layout-gradio
```

Override it before launch with `ENVIRA_WEB_OUTPUT_ROOT`. Each document uses a sanitized original stem plus a content-hash identifier, and each submission adds a UTC timestamp and random run ID. Final overlays are stored below the run's `overlays/` directory and the same files are displayed in the Gradio Gallery.

The UI reads those persistent overlay files into in-memory RGB images before returning them to Gradio. This lets Gradio create safe presentation-cache files without granting web access to the Google Drive output tree or its internal JSON and diagnostic artifacts.

The persistent tree also retains the source copy, rendered pages, pipeline JSON/JSONL/CSV artifacts, manifest, event log, configuration, diagnostics, and terminal status marker according to pipeline privacy settings. Gradio never exposes those internal artifacts.

Temporary uploaded and working files use `ENVIRA_WEB_TEMP_ROOT` (default `/content/envira-layout-web`) and are deleted at the end of each request. Persistent output paths are never cleaned by the temporary workspace manager.

## Optional Python launch

```bash
python -m pip install -e .
export ENVIRA_WEB_OUTPUT_ROOT=/path/to/mounted/persistent/storage
envira-layout-web
```

The Python command and notebook call the same application factory. The notebook remains the primary supported user workflow.

## Configuration

- `config/default.yaml`: pipeline defaults.
- `config/colab.yaml`: reference Colab runtime profile.
- `ENVIRA_WEB_OUTPUT_ROOT`: mandatory persistent destination in practical deployments.
- `ENVIRA_WEB_TEMP_ROOT`: local disposable workspace root.
- `ENVIRA_WEB_CONFIG`: alternate pipeline YAML profile.
- `ENVIRA_WEB_CONCURRENCY`: queue concurrency; defaults to one for model safety.
- `ENVIRA_WEB_MAX_UPLOAD_BYTES`: web upload ceiling.

The Docling model policy is inherited from the pipeline configuration. Provision the saved model artifacts under `<output-root>/artifacts/docling_models`, or explicitly change the model acquisition policy in a reviewed configuration profile.

## UI contract

Visible processing output is limited to the final semantic overlay PNGs in page order. The status area contains operational messages only. Extracted text, coordinates, raw detections, JSON, diagnostics, tracebacks, and Drive paths are not rendered in the interface.
