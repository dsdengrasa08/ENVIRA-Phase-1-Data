# Core strangler migration

The literal notebook extraction is frozen in `preserved_core.py`. It is a compatibility
engine, not the target architecture: it still performs filesystem writes and temporarily
maps typed configuration back to `PHASE1_*` variables. Calls are serialized by a reentrant
lock, so concurrent callers cannot corrupt one another's environment, but the capability
record truthfully reports that the engine is not reentrant, environment-isolated, or
side-effect-free.

`independent_core.py` is the stable dispatcher. `CoreConfig.implementation` supports
`preserved`, `extracted`, and `shadow_compare`; `compare_with_preserved` enables shadow
comparison while selecting `extracted`. Shadow results compare stable IDs, exclusions,
and geometry and may fail closed on any difference.

New stages must implement the immutable `CoreInputs` / `StageOutput` boundary in
`core_contracts.py`. Analysis, decision, and application should remain separate; stages
must not read environment variables or write artifacts. Only `export.py` publishes files.

The preserved engine may be deleted when all of these gates hold:

1. no processing code reads or mutates `PHASE1_*` variables;
2. no processing stage writes files;
3. bootstrap, identity, conversion, and export logic have one package owner;
4. every stage has typed behavioral characterization fixtures;
5. deterministic concurrent/reentrant tests pass;
6. corpus shadow comparisons satisfy the release threshold; and
7. no production import references `preserved_core.py`.
