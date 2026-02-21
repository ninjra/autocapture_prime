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

## Operator Rules (Hard Gate)
- Commands shown to the user MUST be short, one-line, no line breaks, and practical to paste/run directly.
- Before any file/code change:
  - Print the full available skills list.
  - State selected skill(s) and rationale.
  - If no specialized skill is needed, state that explicitly.
- If this sequence is not followed, stop, acknowledge, and restart from the skill-list step before continuing.

## Output Formatting (Hard Gate)
- For Y/N status lists, render `Y` and `N` with raw ANSI escapes (not escaped text, not HTML):
  - Green `Y`: `[32mY[0m`
  - Red `N`: `[31mN[0m`
- Status line format is strict: `<colored Y|N>:<identifier>`
- Do not output literal `\x1b[...]` sequences; output real ANSI control characters.

## Codex CLI Theme (Hard Gate)
- Applies to all assistant prose in Codex CLI for this repo (not only report files).
- Use soft cyberpunk ANSI palette:
  - Header: `38;5;177`
  - Label/key: `38;5;111`
  - Value: `38;5;150`
  - Accounting-month value: `38;5;117`
  - Close-static value: `38;5;81`
  - Close-dynamic value: `38;5;183`
  - Dim/supporting text: `90`
- Separators must be bright white (`97`) and visually emphasized:
  - `/` in triplets (`acct/static/dyn`)
  - `;` between metadata items
  - `=` in key/value pairs (`x=y`)
- `x=y` must render with key and value in different colors; `=` must be bright white.
- If `NO_COLOR` is set or output is non-TTY, fall back to plain text while preserving the same structure.
