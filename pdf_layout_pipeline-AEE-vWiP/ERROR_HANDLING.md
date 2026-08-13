# Pipeline failure contract

The package distinguishes configuration/input failures from recoverable failures in
package-owned post-processing stages. `strict` mode raises `PipelineStageError` with
the original exception chained. `report` mode records a structured `PipelineIssue`,
uses the stage's declared conservative fallback, and marks the run `partial`.

| Stage | Report-mode fallback |
|---|---|
| overlap resolution | retain the independent-core region stream |
| nested hierarchy | retain every physical region at top level |
| caption association | retain captions without semantic ownership |
| table context | omit logical table groups |
| caption grouping | omit semantic caption groups |

Configuration, source identity, page-range, and model initialization failures remain
fatal. `KeyboardInterrupt` and `SystemExit` are never converted into partial results.
Page-local OCR failures are recorded with page context; configured count and ratio
budgets prevent widespread page failure from appearing as a usable partial run.

Exports replace individual files atomically, write hashes and byte sizes to
`artifact_manifest.json`, emit `page_diagnostics.jsonl`, and finish with exactly one
completion marker. `_SUCCESS` means complete or complete-with-warnings, `_PARTIAL`
means declared fallbacks or failed pages were retained, and `_FAILED` means no usable
result was produced.
