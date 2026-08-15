# ENVIRA Gradio PDF Layout Application

This directory is a self-contained web application. It reproduces the maintained
ENVIRA PDF layout workflow inside the `envira_gradio` package and does not import
the repository's reference implementation at runtime.

## Colab (primary workflow)

1. Open `run_gradio_web_app.ipynb` in Google Colab.
2. Select **Runtime → Run all**.
3. The notebook reuses an existing checkout or clones the repository only when it
   is missing, installs this standalone package, mounts Google Drive, initializes
   Docling once, and starts Gradio.
4. Upload one PDF. The interface displays only the final semantic layout overlays.

Persistent inputs, pipeline artifacts, final overlays, manifests, and terminal
status markers are stored below the configured Google Drive root. Gradio upload
files and request staging data remain temporary and are cleaned after each request.

## Local launch

Install the standalone directory, configure a writable persistent root and a valid
Docling model cache, then use the public factories:

```python
from pathlib import Path
from envira_gradio import create_app, initialize_application
from envira_gradio.settings import AppSettings

settings = AppSettings(
    persistent_root=Path("./persistent"),
    config_path=Path("./config/default.yaml"),
)
runtime = initialize_application(settings)
create_app(runtime).queue().launch()
```

## Architecture

- `app.py`: host-facing initialization and Gradio factory.
- `ui/`: PDF upload and overlay-only Gallery.
- `service/`: request lifecycle, temporary staging, serialization, and safe result contract.
- `pipeline/`: independent layout detection, post-processing, export, and validation.
- `config/`: maintained semantic defaults and Colab profile.

The processing service serializes model work because the compatibility core is not
reentrant. A timestamp plus random run ID prevents repeat-upload collisions.
