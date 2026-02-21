# Implementation Spec (Phased)

## Principle
Implement 100% of the recommendations and constraints. Phasing is ordering only, not scope reduction.

## Phase 0 (Stabilize & Make Status Obvious)
- No-deletion mode (remove delete endpoints, disable retention pruning)
- Memory Replacement (Raw) capture preset
- Capture health/status UI + tray parity
- Foreground gating: processing pauses when user active

## Phase 1 (Provable Processing)
- JobRun model + DAG UI
- Proof chips per answer (job_id + hashes)
- Citations-required answers default

## Phase 2 (Retention & Migration)
- Segment store option + sharded standalone files
- Encrypted backup + restore workflow
- Archive/migrate flows (no deletion)

## Phase 3 (Plugin Hardening)
- Atomic install/update/rollback
- Two-phase enable + sandboxing
- Permission UX + PolicyGate tightening

## Completion Checklist
- Localhost-only enforced (bind + firewall)
- CPU/RAM caps enforced with Job Objects
- Startup integrity sweep implemented
- Daily freeze checkpoints implemented
- Export is sanitized-only and does not mutate local raw
- Golden + chaos + migration + e2e tests pass
