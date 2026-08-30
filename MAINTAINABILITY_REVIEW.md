# Maintainability review

**Scope:** repository-wide review, with the actively packaged implementation in
`pdf_layout_pipeline-AEE-vWiP/` treated as the production candidate.

**Review date:** 2026-08-30

## Executive assessment

The active package has a notably strong functional safety net: its behavior is
covered by unit, integration, regression, security, packaging, and performance
tests; public artifacts have schemas; and the CI matrix spans every supported
Python minor version. The main obstacle to calling the repository
well-maintained is therefore not missing functionality. It is that the source
of truth and the routine maintenance contract are unclear.

The highest-value work is to establish one canonical package, make all routine
quality checks executable in CI, and then reduce the very large legacy module
behind characterized interfaces. Do those in that order. A broad rewrite of
the pipeline would create more risk than value while repository ownership and
quality gates remain implicit.

## Evidence and baseline

The following snapshot is intentionally reproducible rather than based on an
impressionistic score:

| Signal | Observed baseline | Interpretation |
| --- | ---: | --- |
| Tracked top-level package copies | 7 directories | It is difficult to identify the supported source of truth. |
| Active source | 29,375 Python lines | A substantial package that benefits from automated static checks. |
| Active tests | 6,177 Python lines | Good behavioral investment, though line count is not a coverage measure. |
| `preserved_core.py` | 15,582 lines | More than half of active source is one migration boundary. |
| `table_context.py` | 1,482 lines | A second useful decomposition candidate. |
| `config.py` | 922 lines | Configuration complexity deserves schema and compatibility discipline. |
| CI Python matrix | 3.10, 3.11, 3.12, 3.13 | Matches the declared `>=3.10` support floor well. |
| Automated formatter, linter, type checker, coverage floor | none configured | Reviewers must enforce routine consistency manually. |

Reproduce the size snapshot from the repository root:

```bash
find pdf_layout_pipeline-AEE-vWiP/src -name '*.py' -print0 | xargs -0 wc -l
find pdf_layout_pipeline-AEE-vWiP/tests -name '*.py' -print0 | xargs -0 wc -l
git ls-files | awk -F/ '{print $1}' | sort | uniq -c | sort -nr
```

## Prioritized findings

### P0 — Declare one supported source tree

The repository tracks the active package beside `pdf_layout_pipeline-vBackup`,
`pdf_layout_pipeline-AEE-vBckp`, and three `pdf_layout_pipeline-AEE-vWiP-Bckp*`
snapshots. Their similar names and overlapping content make accidental edits,
stale security fixes, misleading search results, and copy-based merges likely.
The CI workflow only validates `pdf_layout_pipeline-AEE-vWiP`, but that fact is
not expressed as a repository policy.

**Recommendation**

1. Designate `pdf_layout_pipeline-AEE-vWiP/` as canonical in the root README.
2. Tag the current repository state so history remains discoverable.
3. Remove tracked backup trees in a dedicated, reviewable change. If a snapshot
   has historical value, preserve it in Git history or a release artifact—not
   beside live code.
4. Move the web app and canonical library into explicit top-level `apps/` and
   `packages/` directories only if both are independently supported. Avoid a
   large path migration until backups are gone.

**Done when:** a newcomer can identify the canonical package and CI entry point
from the root in under one minute, and repository-wide search returns only live
implementations by default.

### P0 — Turn the maintenance contract into executable gates

`pyproject.toml` configures packaging and pytest, while CI runs tests, package
inspection, dependency auditing, an SBOM build, and a wheel smoke test. Those
are excellent release checks. It does not currently configure or run a
formatter, linter, type checker, coverage threshold, or documentation/link
check. This leaves import order, dead code, typing regressions, complexity, and
formatting to individual reviewers.

**Recommendation**

- Add Ruff formatting and linting with a deliberately small initial ruleset.
- Add mypy or Pyright incrementally. Start with new modular code and public
  boundaries; exclude `preserved_core.py` temporarily with an explicit removal
  milestone rather than flooding the code with suppressions.
- Measure coverage before choosing a threshold. Ratchet the checked-in floor
  upward; do not select an arbitrary high number that incentivizes weak tests.
- Add a fast `quality` CI job (format check, lint, type check, unit tests) before
  expensive distribution and dependency-audit jobs.
- Provide the same commands through `make`, `tox`, `nox`, or documented
  `python -m ...` invocations so local and CI behavior cannot drift.

**Done when:** one documented command reproduces every required PR check on a
clean checkout, and CI fails on formatting, linting, typing, or coverage
regressions.

### P1 — Decompose the preserved core by behavior, not by file size alone

`preserved_core.py` is explicitly a compatibility boundary, but at 15,582 lines
it concentrates unrelated behavior and makes ownership, review, static
analysis, and safe deletion difficult. The modular pipeline already supplies a
better destination: focused modules such as geometry, reading order, overlap
resolution, filtering, and schema handling.

**Recommendation**

1. Inventory functions in `preserved_core.py` and map every public or indirect
   caller before moving code.
2. Add characterization tests at each boundary, especially for dataframe
   mutation, ordering, coordinate conventions, and empty/malformed inputs.
3. Move one cohesive behavior at a time into the existing domain module.
4. Keep a compatibility import or thin adapter during one deprecation window.
5. Record migration progress and remaining symbols in `CORE_MIGRATION.md`.
6. Reject new business logic in `preserved_core.py` through review policy (and,
   if churn continues, a simple allow-list check).

`table_context.py` and `config.py` should be assessed next, but only split them
where stable domain boundaries emerge. Small files are not an end in themselves.

**Done when:** `preserved_core.py` contains only documented adapters scheduled
for removal, each extraction is behavior-preserving, and no production caller
imports internal legacy implementation details.

### P1 — Add an explicit contributor and ownership path

The active README explains execution and many domain behaviors, but there is no
root orientation, contribution guide, code-owner map, support policy, or issue
template. Operational knowledge is consequently embedded in the current team.

**Recommendation**

- Add a short root `README.md` that identifies supported components, status,
  maintainers, and the canonical setup/test commands.
- Add `CONTRIBUTING.md` covering environment setup, quality commands, test
  taxonomy, schema changes, regression-fixture review, changelog expectations,
  and the release process.
- Add `CODEOWNERS` for pipeline, schemas, security/supply chain, and web app.
- Adopt lightweight pull-request and issue templates with risk, compatibility,
  test evidence, and migration fields.
- State supported Python versions, versioning policy, deprecation window, and
  security-reporting channel in one discoverable support policy.

**Done when:** a contributor can prepare a conforming change without private
instructions, and each sensitive area has an accountable reviewer.

### P1 — Make dependency updates routine and deterministic

Runtime dependencies use sensible major-version bounds, and CI installs through
`constraints-regression.txt`. However, maintainability also requires a visible
refresh cadence and a documented distinction between direct requirements,
reproducible CI constraints, and optional heavyweight model/OCR dependencies.

**Recommendation**

- Automate weekly grouped dependency PRs (Dependabot or Renovate).
- Document how and when `constraints-regression.txt` is regenerated and tested.
- Keep direct intent in `pyproject.toml`; do not hand-edit transitive constraints
  without recording why.
- Cache downloads without caching mutable runtime state, and keep the existing
  audit, SBOM, pinned Actions, and clean-wheel checks.
- Define who evaluates audit exceptions, where they expire, and how urgent
  security upgrades bypass the normal release cadence.

**Done when:** a fresh environment can be reproduced, dependency updates arrive
automatically, and every vulnerability exception has an owner and expiry date.

### P2 — Separate reference documentation from decision records

The package has valuable focused documents for schemas, errors, observability,
security, supply chain, heuristics, and core migration. What is missing is a
small navigation layer and a record of why cross-cutting decisions were made.

**Recommendation**

- Add a documentation index and link it from both root and package READMEs.
- Introduce short architecture decision records for compatibility policy,
  coordinate systems, schema evolution, artifact validation, and the eventual
  retirement of notebook/legacy entry points.
- Assign an owner and `last reviewed` date to operational documents.
- Check internal links in CI and test examples that are intended to be copied.

**Done when:** current behavior lives in reference docs, consequential choices
live in immutable decision records, and stale operational guidance is visible.

## Recommended 90-day sequence

### Days 0–30: make the repository legible

- Publish a root orientation and canonical-source policy.
- Remove backup copies after tagging the baseline.
- Add contribution, ownership, support, and PR templates.
- Capture current test coverage and CI duration; publish both as baselines.

### Days 31–60: automate routine quality

- Land formatter and low-noise lint rules; format once in an isolated commit.
- Establish the local/CI `quality` command and coverage ratchet.
- Enable dependency update automation and document constraints refreshes.
- Start typed public boundaries while explicitly quarantining legacy code.

### Days 61–90: reduce structural risk

- Extract the first characterized behavior from `preserved_core.py`.
- Add architecture decision records and documentation link checking.
- Review flaky/slow test data and split fast PR checks from scheduled exhaustive
  model or OCR checks.
- Review metrics and choose the next extraction based on change frequency and
  defect history, not file size alone.

## Proposed pull-request checklist

- [ ] The change has one clear purpose and updates the canonical tree only.
- [ ] Public behavior, schema, and compatibility effects are described.
- [ ] Tests cover success, boundary, and failure behavior where applicable.
- [ ] Formatting, linting, typing, unit, and relevant regression checks pass.
- [ ] User, operator, security, and migration documentation is updated.
- [ ] New dependencies are justified; generated constraints and SBOM remain valid.
- [ ] Risky changes include rollback or feature-disable instructions.

## Success measures

Track trends rather than rewarding a single vanity score:

- time from clean checkout to first successful local test run;
- median PR lead time and reviewer rework cycles;
- flaky-test rate and p95 CI duration;
- escaped regressions by subsystem;
- percentage of public/module boundaries checked by the chosen type checker;
- coverage change on touched code, alongside mutation or fault-injection checks
  for critical policies;
- remaining callers and lines in `preserved_core.py`;
- age of dependency-update PRs and vulnerability exceptions;
- percentage of operational documents reviewed within their stated interval.

Do **not** set targets such as “100% coverage” or “all files under 500 lines.”
The desired outcome is faster, safer change—not optimizing proxies.
