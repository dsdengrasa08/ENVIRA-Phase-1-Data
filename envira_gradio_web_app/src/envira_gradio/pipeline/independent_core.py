"""Small core dispatcher; the frozen notebook extraction lives in preserved_core."""

from __future__ import annotations

from .core_contracts import (
    CoreCapabilities,
    compare_core_results,
    legacy_environment_report,
)
from .preserved_core import run_preserved_core

PRESERVED_CAPABILITIES = CoreCapabilities(
    implementation="preserved",
    thread_safe=True,  # serialized by the compatibility-engine lock
    reentrant=False,
    process_environment_isolated=False,
    processing_side_effect_free=False,
)


def run_extracted_core(conversion, page_set, config):
    """Run extracted package stages.

    The final legacy filter sequence remains delegated during the strangler migration;
    all post-core stages are already package-owned and typed. The diagnostic capability
    record prevents callers from mistaking this transitional adapter for completion.
    """
    result = run_preserved_core(conversion, page_set, config)
    result.diagnostics["core_capabilities"] = {
        **PRESERVED_CAPABILITIES.to_dict(),
        "implementation": "extracted_adapter",
        "migration_complete": False,
    }
    return result


def run_independent_core(conversion, page_set, config):
    """Select preserved, extracted-adapter, or shadow-comparison execution."""
    mode = config.core.implementation
    if mode == "preserved":
        result = run_preserved_core(conversion, page_set, config)
        result.diagnostics["core_capabilities"] = PRESERVED_CAPABILITIES.to_dict()
        result.diagnostics["legacy_environment"] = legacy_environment_report(config)
        return result
    if mode == "extracted" and not config.core.compare_with_preserved:
        result = run_extracted_core(conversion, page_set, config)
        result.diagnostics["legacy_environment"] = legacy_environment_report(config)
        return result
    preserved = run_preserved_core(conversion, page_set, config)
    candidate = run_extracted_core(conversion, page_set, config)
    comparison = compare_core_results(preserved, candidate)
    candidate.diagnostics["core_shadow_comparison"] = comparison
    candidate.diagnostics["legacy_environment"] = legacy_environment_report(config)
    if config.core.fail_on_difference and not comparison["equivalent"]:
        raise RuntimeError("preserved/extracted core shadow comparison diverged")
    return candidate


__all__ = ["run_independent_core", "run_extracted_core", "PRESERVED_CAPABILITIES"]
