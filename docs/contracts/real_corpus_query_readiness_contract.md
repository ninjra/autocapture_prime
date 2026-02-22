# Real-Corpus Query Readiness Contract

## Purpose
Define release-blocking readiness for memory quality against real captured corpus.

## Gate Priority
1. Tier A (blocking): real-corpus strict expected-answer gate.
2. Tier B (blocking): Stage1 completeness and retention marker validity.
3. Tier C (non-blocking): synthetic regression confidence.

Synthetic pass never overrides real-corpus strict failure.

## Strict Source Of Truth
- Contract file: `docs/contracts/real_corpus_expected_answers_v1.json`
- Initial strict suite: `advanced20` (`Q1..Q10`, `H1..H10`)
- Required strict semantics:
  - `matrix_total == expected_total_from_contract`
  - `matrix_evaluated == expected_total_from_contract`
  - `matrix_skipped == 0`
  - `matrix_failed == 0`

## Generic Policy
- `generic20` is non-blocking informational telemetry.
- Generic failures are still reported and trended, but do not block release.

## Query Contract (Blocking)
- Query path is read-only.
- `schedule_extract=false` performs no extraction scheduling.
- No raw media reads in query path.
- Deterministic "not available yet" response when evidence is insufficient.

## Metrics Contract
- Required output artifacts:
  - `artifacts/real_corpus_gauntlet/<ts>/strict_matrix.json`
  - `artifacts/real_corpus_gauntlet/<ts>/metrics.json`
  - `artifacts/real_corpus_gauntlet/<ts>/query_results.json`
  - `docs/reports/real_corpus_strict_latest.md`
- Required query contract metrics (strict runs):
  - `query_extractor_launch_total == 0`
  - `query_schedule_extract_requests_total == 0`
  - `query_raw_media_reads_total == 0`
  - `query_latency_p95_ms <= 1500`
