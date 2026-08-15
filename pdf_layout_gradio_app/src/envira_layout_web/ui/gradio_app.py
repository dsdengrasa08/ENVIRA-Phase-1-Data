"""Gradio interface exposing only final semantic overlay images."""

from __future__ import annotations
import logging

import gradio as gr

from ..errors import WebAppError
from ..services.processing import ProcessingService

LOGGER = logging.getLogger(__name__)


def build_gradio_app(processing: ProcessingService) -> gr.Blocks:
    with gr.Blocks(title="ENVIRA PDF Layout Detection") as demo:
        gr.Markdown("# ENVIRA PDF Layout Detection\nUpload a PDF to display detected layout regions on each page.")
        upload = gr.File(label="PDF file", file_types=[".pdf"], type="filepath")
        process_button = gr.Button("Process PDF", variant="primary")
        status = gr.Markdown("Ready.")
        gallery = gr.Gallery(
            label="Detected layout overlays",
            columns=1,
            object_fit="contain",
            height="auto",
        )

        def process_upload(uploaded_path: str | None, progress=gr.Progress()):
            if not uploaded_path:
                return [], "Select a PDF before starting."
            try:
                progress(0.05, desc="Validating PDF")
                result = processing.process(uploaded_path)
                progress(1.0, desc="Complete")
                images = [(str(path), f"Page {index}") for index, path in enumerate(result.overlay_paths, 1)]
                qualifier = " with warnings" if result.status != "complete" else ""
                return images, f"Complete{qualifier} — {result.page_count} page(s) processed."
            except WebAppError as exc:
                return [], str(exc)
            except Exception:
                LOGGER.exception("Unexpected PDF processing failure")
                return [], "Layout processing failed. Please check the persistent run logs."

        process_button.click(
            process_upload,
            inputs=upload,
            outputs=[gallery, status],
            show_progress="full",
        )
    return demo
