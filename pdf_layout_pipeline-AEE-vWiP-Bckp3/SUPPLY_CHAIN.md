# Dependency, model, and release provenance

`pyproject.toml` is the authoritative direct-dependency contract. The regression
constraints are a deliberately reviewed direct-pin overlay and are automatically checked
against every project specifier. Production deployments should generate a complete,
platform-specific transitive lock with hashes and install it using `--require-hashes` and
`--only-binary=:all:`; a direct constraints file is not represented as a full lock.

CI tests Python 3.10–3.13, checks the resolved environment, builds wheel and sdist once,
inspects their contents, audits dependencies, generates a CycloneDX SBOM, and smoke-tests
the wheel from `/tmp` so repository `src` injection cannot mask packaging defects. Release
tags must match wheel metadata. Actions are pinned to immutable revisions and workflow
permissions are read-only.

Saved models require `model-manifest.json` by default. The manifest identifies backend,
backend version, model set, relative file paths, sizes, and SHA-256 digests. Readiness is
based on that verified inventory—not filename suffixes or directory size. Downloads use a
timeout and staging directory; only a verified set is atomically promoted, preserving the
known-good set until verification succeeds.

For compatibility with model caches created before manifests existed (including the
original Google Drive/Colab cache), `bootstrap_legacy_model_manifest` defaults to `true`.
On the first run only, the pipeline inventories and hashes the existing cache, writes the
manifest atomically, labels its provenance as local trust-on-first-use, and then validates
it normally. Later modifications fail closed. Set this option to `false` in deployments
that require a separately approved manifest and do not permit local bootstrapping.

Every application run records the full installed distribution inventory digest, verified
model-manifest and model-file-set digests, backend capability record, effective-config
digest, Python/platform identity, and a canonical environment fingerprint. Regression
differences must therefore be reviewed alongside environment-fingerprint changes; golden
updates require an explicit reason and must not silently absorb dependency/model changes.
