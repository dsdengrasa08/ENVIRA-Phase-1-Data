"""Compatibility alias for the package-owned core layout implementation.

The production pipeline no longer reads or executes a notebook. This module is
retained temporarily so external imports of ``run_authoritative_pipeline`` keep
working while callers migrate to :func:`independent_core.run_independent_core`.
"""

from __future__ import annotations

from .independent_core import run_independent_core


def run_authoritative_pipeline(conversion, page_set, config):
    """Run the independent core under the former public compatibility name."""
    return run_independent_core(conversion, page_set, config)


__all__ = ["run_authoritative_pipeline"]
