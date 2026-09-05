# Data requirements

The runtime accepts PDF files. Inputs may be malformed or sensitive and must be handled as untrusted data. Do not commit private papers or extracted content. Place small redistributable or synthetic examples in `data/sample`; keep acquired data under ignored `data/external` or `data/raw` locations.

Every evaluation corpus needs a manifest containing stable document IDs, SHA-256 hashes, licensing/access notes, strata, and inclusion/exclusion criteria. Keep the manifest private when even filenames or hashes are sensitive.
