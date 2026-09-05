# Architecture

`envira_pdf_layout` is the only authoritative implementation of the layout method. Interfaces depend inward on its public API: the CLI belongs to the library, while `envira_gradio` adapts uploads and presentation without owning pipeline algorithms.

A run flows through input validation, runtime/model preparation, backend conversion, deterministic post-processing stages, artifact export, and post-export validation. Internal code should pass immutable typed configuration and domain records; environment variables and JSON-compatible dictionaries are compatibility and serialization boundaries.

The legacy compatibility core remains serialized and is being replaced stage by stage under semantic equivalence tests. New application code must not import or copy private compatibility implementation details.
