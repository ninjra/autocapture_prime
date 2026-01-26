# Risk register

| Risk | Impact | Likelihood | Mitigation | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Video container choice (replace zip-of-JPEG) | High (format stability + tooling) | Medium | Define versioned container spec; keep legacy zip as explicit compat; add deterministic reader tests. | TODO | Open |
| Windows-only APIs (DPAPI, job objects, Desktop Duplication) | High (platform divergence) | Medium | Add thin abstraction layer; mock in CI; keep real paths on Windows with explicit tests. | TODO | Open |
| Dependency lock tooling unavailable offline | Medium (supply chain gate) | High | Add lockfile strategy with TODO for tool; allow offline base install; doctor warns when lock missing. | TODO | Open |
| SQLCipher availability | Medium (default encryption backend) | Medium | Fallback to encrypted store; feature flags and doctor warnings; optional extra. | TODO | Open |
| Web console scope creep | Medium (phase 7 delays) | Medium | Limit to required panels and endpoints; use facade for parity; keep UI optional if deps unavailable. | TODO | Open |
| Evidence immutability regression | High (pillar violation) | Medium | Add immutability gate and tests; enforce put_new vs put_replace semantics. | TODO | Open |
| Performance regressions under ACTIVE | High (P1 regression) | Medium | Deterministic perf gates; isolate heavy work to IDLE; enforce scheduler rules. | TODO | Open |
| Storage migration correctness | High (data loss risk) | Medium | Copy+verify migrations only; no auto-delete; add recovery scanner and tests. | TODO | Open |
