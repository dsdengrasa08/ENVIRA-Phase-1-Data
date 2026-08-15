"""Gradio interface containing only PDF input and final page overlays."""

from __future__ import annotations

import logging


LOGGER = logging.getLogger(__name__)


def build_interface(service, max_concurrency: int = 1):
    import gradio as gr

    def handle(uploaded_pdf, progress=gr.Progress()):
        try:
            return service.process(uploaded_pdf, progress)
        except ValueError as exc:
            raise gr.Error(str(exc)) from None
        except Exception:
            LOGGER.exception("ENVIRA PDF processing failed")
            raise gr.Error("PDF processing failed. Check the persistent run records for details.") from None

    with gr.Blocks(title="ENVIRA PDF Layout Detection") as demo:
        gr.Markdown("# ENVIRA PDF Layout Detection\nUpload a PDF to view its detected page layouts.")
        upload = gr.File(label="PDF", file_types=[".pdf"], type="filepath")
        process = gr.Button("Process PDF", variant="primary")
        gallery = gr.Gallery(
            label="Detected layout pages",
            columns=1,
            object_fit="contain",
            height="auto",
            preview=True,
        )
        process.click(handle, inputs=upload, outputs=gallery, concurrency_limit=max_concurrency)
        upload.clear(lambda: [], outputs=gallery, queue=False)
    return demo
