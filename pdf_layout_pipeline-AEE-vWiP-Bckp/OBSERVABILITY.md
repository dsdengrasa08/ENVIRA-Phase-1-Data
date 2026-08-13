# Operational observability

The package keeps deterministic semantic `stage_trace.jsonl` records separate from
the timestamped operational `run_events.jsonl` stream. Events use a versioned,
vendor-neutral envelope with run/document correlation, status, duration, bounded
counters, and sanitized issues. Callers may pass an event sink to `run_pdf`; sink
failures are recorded and never mutate semantic pipeline state.

Every non-resumed run emits one terminal `run_completed`, `run_failed`, or
`run_cancelled` event. Failures also produce an atomic, sanitized `run_failure.json`.
Private tracebacks are disabled by default. Cooperative cancellation and the optional
total-run deadline are checked between application boundaries and package-owned stages.

Use `envira-pdf-layout doctor --config PROFILE` before scheduled work to verify the
configuration, output write access, free disk, model manifest, Docling, OCR status,
and packaged schemas without processing a PDF. Operational counters deliberately avoid
document IDs, paths, raw errors, and region IDs as metric labels to prevent cardinality
and privacy problems.

Initial service-level indicators should include successful/partial run ratios, failed
page ratio, p50/p95 duration per page and stage, conversion throughput, model and
artifact-validation duration, validation failures, retry success, disk use, and peak
memory. Establish alert thresholds only after measuring a representative corpus.
