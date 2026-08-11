"""Public layout pipeline entry point."""

from __future__ import annotations

from .authoritative import run_authoritative_pipeline
from .table_context import associate_table_context


def run_layout_pipeline(conversion, page_set, config):
    """Run authoritative layout processing, then infer logical table groups."""
    result = run_authoritative_pipeline(conversion, page_set, config)
    if config.table_context.enabled:
        result.logical_tables = associate_table_context(
            result.final_regions,
            result.pages,
            document_id=result.document.doc_id,
            config=config.table_context,
        )
        groups_by_page: dict[int, list[dict]] = {}
        for group in result.logical_tables:
            groups_by_page.setdefault(group["page_number"], []).append(group)
        for page in result.pages:
            page["logical_tables"] = groups_by_page.get(page["page_number"], [])
        result.diagnostics["table_context"] = {
            "table_count": len(result.logical_tables),
            "associations": [
                association
                for group in result.logical_tables
                for association in group["associations"]
            ],
        }
    return result
