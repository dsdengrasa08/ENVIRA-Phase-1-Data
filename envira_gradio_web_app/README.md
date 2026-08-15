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

For notebook/Colab use, prefer `launch_application(demo)`. It prevents duplicate
servers when the launch cell is rerun and otherwise delegates public sharing and
Colab inline presentation directly to Gradio. `close_application(demo)` stops only
the Gradio server; it does not terminate the Colab runtime. Closing the browser tab
does not stop either one.

## Architecture

- `app.py`: host-facing initialization and Gradio factory.
- `ui/`: PDF upload and overlay-only Gallery.
- `service/`: request lifecycle, temporary staging, serialization, and safe result contract.
- `pipeline/`: independent layout detection, post-processing, export, and validation.
- `config/`: maintained semantic defaults and Colab profile.

The processing service serializes model work because the compatibility core is not
reentrant. A timestamp plus random run ID prevents repeat-upload collisions.

## Runtime warnings and failure diagnostics

Docling may emit Transformers warnings while it loads its bundled layout, formula,
or vision-language models. Messages about `torch_dtype`, token IDs, tied weights,
or generation arguments originate in the installed Docling/Transformers model
stack. They are warnings rather than pipeline failures and are intentionally not
hidden, because hiding all third-party warnings could conceal a future compatibility
problem. Keep the tested dependency ranges current when upgrading Docling.

The application uses the supported `pymupdf` import name and does not use the
deprecated `fitz` compatibility import. If a `fitz` deprecation warning remains,
it originates in an installed dependency and should be addressed by upgrading that
dependency rather than suppressing warnings globally.

The Gradio interface deliberately shows a generic error so internal paths and
processing details are not exposed to web users. The complete exception is logged
to the Colab/server console and, after a run directory has been created, recorded
in the private `run_failure.json` file in that run's persistent output directory.

Final overlays are loaded from their validated Google Drive copies into detached
RGB images before they are returned to `gr.Gallery`. The application intentionally
does not pass Drive paths to Gradio or add the persistent root to `allowed_paths`:
that avoids both Gradio file-route rejections and accidental web access to the raw
JSON, extracted text, manifests, and other private artifacts stored beside overlays.

If the console says `Could not create share link`, layout processing has not failed:
the external Gradio tunnel service is unreachable. Gradio's own Colab inline
presentation remains available. A Colab runtime restart/disconnect still terminates
the server and clears in-memory models, while completed Drive outputs remain.

Creating a Gradio share URL requires broker discovery, an `frpc` binary, and an
outbound connection to the returned tunnel endpoint. Colab, a network proxy,
regional filtering, or a Gradio service incident can block those steps. The launcher
does not duplicate, retry, or gate Gradio's broker request: one native
`demo.launch(share=True, inline=True)` call owns both the public URL and Colab
presentation. Local non-secret diagnostics report the installed Gradio version,
Colab detection, tunnel-binary readiness, certificate-directory writability, and
whether a proxy is configured. A missing public URL does not change PDF processing
or Google Drive persistence.
