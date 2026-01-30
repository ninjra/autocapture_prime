# Agents Operating Manual

## Mission
- Implement ALL requirements in BLUEPRINT.md with no omissions.
- Optimize for: Performance, Accuracy, Security, Citeability.

## Non-Negotiables
- Localhost-only: never bind beyond 127.0.0.1; fail closed.
- No local deletion: no delete endpoints; no retention pruning; archive/migrate only.
- Raw-first local store: no masking/filtering locally; sanitization only on explicit export.
- Foreground gating: when user is ACTIVE, only capture+kernel runs; pause all other processing.
- Idle budgets: CPU <= 50% and RAM <= 50% (enforced), GPU may saturate.
- Answers: citations required by default; never fabricate; clearly say when uncitable/indeterminate.
- Tray: MUST NOT provide capture pause or deletion actions (processing pause OK).

## Implementation Protocol
- For each SRC requirement: reference where it is implemented (module/ADR/test).
- Add/extend tests for every behavior change; prefer deterministic tests.
- Any new privileged behavior must be audited (append-only audit log).
- Treat plugin code and external inputs as untrusted; enforce PolicyGate and sandbox.

## Definition of Done
- All test suites in MOD-021 pass.
- Coverage_Map is satisfied: every SRC implemented and verifiable.
