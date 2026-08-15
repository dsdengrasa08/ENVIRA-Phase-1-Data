"""Standalone Gradio application for the ENVIRA PDF layout pipeline."""

from .settings import AppSettings


def create_app(*args, **kwargs):
    """Lazily import the Gradio composition root."""
    from .application import create_app as factory

    return factory(*args, **kwargs)


__all__ = ["AppSettings", "create_app"]
