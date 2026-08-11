"""Public layout pipeline entry point."""

from __future__ import annotations

from .authoritative import run_authoritative_pipeline


def run_layout_pipeline(conversion, page_set, config):
    """Run the immutable reference notebook's detection/post-processing logic."""
    return run_authoritative_pipeline(conversion, page_set, config)
