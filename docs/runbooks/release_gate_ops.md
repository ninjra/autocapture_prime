# Release Gate Ops

## Purpose
Run fail-closed release checks and enforce soak admission criteria for the golden pipeline.

## Single Command
- `bash /mnt/d/projects/autocapture_prime/tools/release_gate.sh`

## Artifacts
- Release gate report: `artifacts/release/release_gate_latest.json`
- Soak precheck report: `artifacts/soak/golden_qh/admission_precheck_latest.json`
- Soak postcheck report: `artifacts/soak/golden_qh/latest/admission_postcheck.json`

## Policy
- Any non-pass status (`warn`, `skip`, `fail`, `error`) fails release.
- Soak start is blocked unless precheck passes:
  - release gate report `ok=true`
  - latest 3 advanced20 runs are strict pass (`20/20`)
  - citation coverage ratio meets threshold.
- Soak postcheck requires:
  - elapsed duration threshold met
  - no failed attempts
  - no VLM-blocked attempts
  - soak summary `ok=true`.

## Override (Debug Only)
- `AUTOCAPTURE_SOAK_SKIP_ADMISSION=1` allows starting soak without precheck.
- Do not use overrides for release decisions.
