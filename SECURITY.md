# Security Policy

Do not open a public issue for a suspected vulnerability or disclose sensitive PDFs, credentials, paths, or extracted content. Report vulnerabilities privately to the repository maintainers with the affected version, impact, and a minimal non-sensitive reproduction.

PDFs and artifact directories are untrusted inputs. Production deployments must use a non-root, resource-limited, network-disabled worker; read-only model mounts; and private work/output volumes. See the [pipeline security guide](docs/reference/pipeline-security.md) for detailed controls and retention guidance.
