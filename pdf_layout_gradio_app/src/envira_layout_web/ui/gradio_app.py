"""Gradio interface exposing only final semantic overlay images."""

from __future__ import annotations
import logging

import gradio as gr

from ..errors import WebAppError
from ..services.processing import ProcessingService
from .presenters import load_overlay_pixels

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
            # A generator lets the status change immediately while the queued
            # pipeline request is running.  Clearing the gallery here also
            # prevents results from a previous document being mistaken for
            # the current document's output.
            if not uploaded_path:
                yield [], "Select a PDF before starting."
                return
            yield [], "Processing PDF…"
            try:
                progress(0.05, desc="Validating PDF")
                result = processing.process(uploaded_path)
                progress(1.0, desc="Complete")
                # Return in-memory RGB images rather than persistent Drive paths.
                # Gradio creates its own cache files for images, avoiding both its
                # external-path restriction and accidental serving of other run
                # artifacts from the persistent output tree.
                images = [
                    (load_overlay_pixels(path), f"Page {index}")
                    for index, path in enumerate(result.overlay_paths, 1)
                ]
                qualifier = " with warnings" if result.status != "complete" else ""
                yield images, f"Complete{qualifier} — {result.page_count} page(s) processed."
            except WebAppError as exc:
                yield [], str(exc)
            except Exception:
                LOGGER.exception("Unexpected PDF processing failure")
                yield [], "Layout processing failed. Please check the persistent run logs."

        process_button.click(
            process_upload,
            inputs=upload,
            outputs=[gallery, status],
            show_progress="full",
        )
    return demo
