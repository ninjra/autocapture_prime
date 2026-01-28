### Minimum acceptance criteria (must pass)

| Area             | Criteria                                                                                              |
| ---------------- | ----------------------------------------------------------------------------------------------------- |
| Determinism      | Same frame stream processed twice yields identical persisted artifact hashes                          |
| Post‑TTL utility | For a fixture stream, queries about table cells and code contents still answerable without images     |
| Action grounding | ActionEvent always references `target_element_id` or explicitly unknown, with confidence and evidence |
| Table fidelity   | Extracted tables preserve row/col counts and stable cell addresses across minor UI motion             |
| Compliance       | No pixels persisted in derived store; redaction passes all secret fixtures                            |

### Performance targets (non-binding defaults; tune as needed)

* Heavy pass only on boundaries
* OCR and parsing complete within an operator-defined budget per boundary state

---

# /docs/codex_prompt_instructions.md

Use this as the “do exactly this” implementation prompt.

### Implementation sequencing (deterministic)

| Step | Implement                                          | Output                                       |
| ---- | -------------------------------------------------- | -------------------------------------------- |
| 1    | `src/core/types.py`, artifact envelope, validators | compile + unit tests pass                    |
| 2    | plugin framework + orchestrator + registry         | run a trivial two-plugin pipeline            |
| 3    | normalize + phash + tile plugins                   | deterministic patch list and hashes          |
| 4    | OCR plugin wrapper (ONNX)                          | tokens with bbox + NMS merge                 |
| 5    | state builder + persistence envelope               | ScreenState persisted                        |
| 6    | temporal segment + delta builder                   | DeltaEvent persisted                         |
| 7    | table + spreadsheet plugins                        | Table artifacts + CSV export                 |
| 8    | code plugin                                        | CodeBlock text + caret/selection best-effort |
| 9    | cursor tracking + action inference                 | ActionEvent with evidence + confidence       |
| 10   | compliance redact + indexing + query API           | queries run on persisted derived artifacts   |
| 11   | regression harness + determinism test              | CI green on golden fixtures                  |

---

## C

**key_claims**

| Claim                                                                                                                                                                                               | Label     |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| Persisting **states + deltas + actions** (not just OCR text) is sufficient to answer most “what changed / what did I do” questions after image TTL, provided provenance and structure are retained. | INFERENCE |
| Pixels-only action attribution must be stored as **probabilistic** (confidence + alternatives + evidence) to avoid false certainty.                                                                 | INFERENCE |
| Table/spreadsheet utility post‑TTL requires **structure-first extraction** and stable cell addressing, not only plain text OCR.                                                                     | INFERENCE |
| Deterministic execution requires canonical hashing, schema validation, stable sorting, and non-sampling model calls.                                                                                | INFERENCE |
| Compliance is enforceable by ensuring the derived store never receives image bytes and by hard-gating persistence on redaction and provenance checks.                                               | INFERENCE |

## D

**per_recommendation** (Gate: **ANY_REGRESS ⇒ DO_NOT_SHIP**)

| Rec                    | improved                         | risked                         | enforcement_location                   | regression_detection                                                |
| ---------------------- | -------------------------------- | ------------------------------ | -------------------------------------- | ------------------------------------------------------------------- |
| DOM-like element graph | grounded UI QA + action targets  | wrong ID mapping → wrong blame | `ui.parse`, `match.ids`, validators    | golden UI fixtures; element-id stability metric; fail if drift      |
| Any-res tiling         | small text/icon recall           | missed ROI → silent omissions  | `preprocess.tile`                      | coverage + “tiny text” fixture suite; fail on recall drop           |
| Table/spreadsheet TSR  | cell-accurate values + addresses | grid errors corrupt meaning    | `extract.table`, `extract.spreadsheet` | cell-address consistency tests; CSV round-trip checks               |
| Chart derender         | numeric QA from plots            | fabricated series values       | `extract.chart` guardrails             | forbid series without tick evidence; unit tests with known plots    |
| Code canonicalization  | indentation-preserving SQL/code  | OCR punctuation errors         | `extract.code` validation              | lexer/balance heuristics; diff vs golden rendered code              |
| Temporal deltas        | change explanation               | animation noise floods deltas  | `temporal.segment`, `build.delta`      | false-delta rate test; volatile-region suppression fixtures         |
| Action inference       | “what did I click/type”          | ambiguity misattributes        | `infer.action`                         | require confidence+alternatives; top-k accuracy on labeled fixtures |
| Derived-only memory    | post‑TTL recall                  | PII retention risk             | `compliance.redact`, `persist`         | secret fixtures; persistence hard-gates; TTL audit tests            |

## E

**DETERMINISM:** VERIFIED
Deterministic under these explicit conditions: fixed plugin order, fixed configs hashed canonically, deterministic model decode (no sampling), stable sorting for all lists, quantized floats before hashing/persistence, and idempotent persistence/index updates.

## F

**TS:** 2026-01-26T20:31:32-07:00 (America/Denver)
**FOOTER:** THREAD=screen-semantic-trace | CHAT_ID=screen-semantic-trace-20260126-203132-MST | TS=2026-01-26T20:31:32-07:00
