# Security and privacy

PDFs and artifact directories are untrusted inputs. Production deployments should run
conversion as a non-root, network-disabled worker with CPU, memory, process, and time
limits; mount model artifacts read-only and expose only a private working/output volume.
Python validation is defense in depth, not a native-parser sandbox.

Exports contain derived document content and must be treated as sensitive. Conservative
defaults omit raw Docling JSON and Markdown, redact secret-looking configuration values,
remove source paths, restrict diagnostics, and create directories/files as `0700`/`0600`.
Region text remains enabled for pipeline consumers but can be disabled with
`privacy.export_region_text`. Debug/full diagnostics require explicit configuration.

Artifact validation rejects absolute/traversal/Windows-drive paths, symlink escapes,
duplicate manifest paths, non-regular files, size mismatches, oversized artifacts, long
JSONL lines, and excessive rows. Hashing and JSONL input are streamed. Resume uses the
full source SHA-256 plus configuration digest and validated artifact hashes; the short
digest is display-only.

Failed artifacts are sensitive. When `privacy.retain_failed_artifacts` is false, service
operators should remove the failed run directory according to their retention policy.
Filesystem deletion is logical deletion and is not guaranteed cryptographic erasure.

Remote backend services are disabled by default. Run private workloads offline and do not
enable model downloads in workers holding cloud credentials. Multi-tenant use requires
process/container isolation because the preserved compatibility core is serialized but
still temporarily maps typed configuration into process environment variables.

Report vulnerabilities privately to the repository maintainers. Releases should include
dependency and secret scans, wheel-content inspection, malicious-manifest tests, and a
sandboxed untrusted-PDF smoke test. Test fixtures and CI artifacts must contain no private
documents or extracted production text.
