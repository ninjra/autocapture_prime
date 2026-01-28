### 1) Runtime checks (must be implemented)

| Check                                     | Enforced in          | Failure behavior                                  |
| ----------------------------------------- | -------------------- | ------------------------------------------------- |
| Schema validation for every plugin output | orchestrator         | plugin output dropped + diagnostic                |
| Bbox bounds check                         | common validator     | clamp not allowed; must drop invalid bbox         |
| Deterministic sort enforcement            | plugin helper        | re-sort + log if out of order                     |
| Provenance completeness                   | persist              | refuse persistence if required provenance missing |
| Redaction completeness                    | compliance.redact    | refuse persistence if sensitive patterns remain   |
| TTL policy metadata present               | persist(image store) | refuse image write                                |

### 2) CI regression harness (golden fixtures)

Use a folder of test assets:

* `tests/fixtures/frames/*.png` (kept only in test env)
* `tests/golden/*.json` expected artifacts (redacted)

CI must run:

* “same input twice” determinism test → identical artifact hashes
* OCR token stability test (within tolerance)
* Table cell address consistency test
* Code indentation stability test
* Delta/action inference smoke tests

### 3) Metrics (numeric only)

Minimum metrics per run:

* `ocr.tokens`, `ocr.avg_conf`
* `ui.elements`
* `table.count`, `table.cells`
* `delta.changes`
* `action.confidence`
* `redaction.count`

---
