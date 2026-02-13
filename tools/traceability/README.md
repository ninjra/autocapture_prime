# Traceability Tooling

This folder contains deterministic tooling that ties together:
- blueprint items (`tools/blueprint_items.json`)
- implementation evidence (`docs/reports/implementation_matrix.md`, `docs/reports/blueprint-gap-*.md`)
- gates/tests that prove each acceptance-criteria bullet is validated

The immediate goal is to make “implemented” a *provable* claim:
- Every acceptance bullet must have at least one deterministic validator.
- Validators must exist and be runnable under MOD-021 (WSL-friendly).

