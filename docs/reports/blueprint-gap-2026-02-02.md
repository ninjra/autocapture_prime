# Blueprint Gap Tracker (Autocapture NX)

Generated: 2026-02-02

Status legend:
- unverified: not audited yet
- implemented: verified by module/test refs
- missing: not implemented

| ID | Phase | Title | Status | Evidence |
| --- | --- | --- | --- | --- |
| I001 | Phase 1 | Eliminate floats from journal/ledger payloads | implemented | autocapture_nx/kernel/canonical_json.py<br>autocapture_nx/kernel/event_builder.py<br>plugins/builtin/journal_basic/plugin.py<br>plugins/builtin/ledger_basic/plugin.py<br>tests/test_canonical_payloads.py |
| I002 | Phase 1 | Make backpressure actually affect capture rate | implemented | plugins/builtin/backpressure_basic/plugin.py<br>plugins/builtin/capture_windows/plugin.py<br>autocapture_nx/windows/win_capture.py<br>tests/test_backpressure.py<br>tests/test_capture_rate.py |
| I003 | Phase 1 | Stop buffering whole segments in RAM; stream segments | implemented | plugins/builtin/capture_windows/plugin.py<br>plugins/builtin/storage_encrypted/plugin.py<br>plugins/builtin/storage_memory/plugin.py<br>tests/test_capture_streaming.py |
| I004 | Phase 1 | Do not write to storage from realtime audio callback | implemented | plugins/builtin/audio_windows/plugin.py<br>tests/test_audio_callback_queue.py |
| I005 | Phase 1 | Stop mutating primary evidence metadata during query | implemented | autocapture_nx/kernel/query.py<br>autocapture_nx/kernel/metadata_store.py<br>tests/test_query_derived_records.py |
| I006 | Phase 1 | Introduce globally unique run/session identifier; prefix all record IDs | implemented | autocapture_nx/kernel/ids.py<br>autocapture_nx/kernel/event_builder.py<br>plugins/builtin/capture_windows/plugin.py<br>plugins/builtin/audio_windows/plugin.py<br>plugins/builtin/input_windows/plugin.py<br>plugins/builtin/window_metadata_windows/plugin.py<br>tests/test_journal_run_id.py<br>tests/test_run_state_entries.py |
| I007 | Phase 1 | Make ledger writing thread-safe | implemented | plugins/builtin/ledger_basic/plugin.py<br>tests/test_ledger_journal_concurrency.py |
| I008 | Phase 1 | Make journal writing thread-safe; centralize sequences | implemented | plugins/builtin/journal_basic/plugin.py<br>tests/test_ledger_journal_concurrency.py |
| I009 | Phase 1 | Fail closed if DPAPI protection fails when encryption_required | implemented | autocapture_nx/kernel/keyring.py<br>plugins/builtin/storage_encrypted/plugin.py<br>tests/test_encrypted_store_fail_loud.py |
| I010 | Phase 1 | Sort all store keys deterministically | implemented | plugins/builtin/storage_encrypted/plugin.py<br>plugins/builtin/storage_memory/plugin.py<br>plugins/builtin/storage_sqlcipher/plugin.py<br>tests/test_storage_encrypted.py |
| I011 | Phase 1 | Use monotonic clocks for segment duration | implemented | plugins/builtin/capture_windows/plugin.py<br>tests/test_capture_monotonic.py |
| I012 | Phase 1 | Align default config with implemented capture backend | implemented | config/default.json<br>plugins/builtin/capture_windows/plugin.py<br>tests/test_capture_backend_default.py |
| I013 | Phase 1 | Remove hard-coded model paths; config-driven + portable | implemented | config/default.json<br>plugins/builtin/embedder_stub/plugin.py<br>plugins/builtin/reranker_stub/plugin.py<br>plugins/builtin/vlm_stub/plugin.py<br>tests/test_model_paths_config.py |
| I014 | Phase 1 | Enforce plugin compat.requires_kernel / schema versions | implemented | autocapture_nx/plugin_system/registry.py<br>tests/test_plugin_loader.py |
| I015 | Phase 1 | Verify contract lock at boot/doctor | implemented | autocapture_nx/kernel/loader.py<br>tests/test_contract_pins.py |
| I016 | Phase 2 | Split capture into grab -> encode/pack -> encrypt/write pipeline | implemented | autocapture_nx/capture/pipeline.py<br>plugins/builtin/capture_windows/plugin.py |
| I017 | Phase 2 | Bounded queues with explicit drop policies | implemented | autocapture_nx/capture/queues.py<br>autocapture_nx/capture/pipeline.py |
| I018 | Phase 2 | Replace zip-of-JPEG with real video container for primary artifact | implemented | autocapture_nx/capture/pipeline.py |
| I019 | Phase 2 | Add GPU-accelerated capture/encode backend (NVENC/DD) | implemented | autocapture_nx/capture/pipeline.py<br>autocapture_nx/windows/win_capture.py |
| I020 | Phase 2 | Record segment start/end timestamps | implemented | autocapture_nx/capture/pipeline.py |
| I021 | Phase 2 | Record capture parameters per segment | implemented | autocapture_nx/capture/pipeline.py |
| I022 | Phase 2 | Correlate frames with active window via synchronized timeline | implemented | plugins/builtin/window_metadata_windows/plugin.py<br>autocapture_nx/capture/pipeline.py |
| I023 | Phase 2 | Add cursor/input correlation timeline references | implemented | plugins/builtin/input_windows/plugin.py<br>plugins/builtin/cursor_windows/plugin.py<br>plugins/builtin/retrieval_basic/plugin.py<br>autocapture_nx/capture/pipeline.py |
| I024 | Phase 2 | Disk pressure degrades capture quality before stopping | implemented | autocapture_nx/capture/pipeline.py |
| I025 | Phase 2 | Atomic segment writes (temp + os.replace) | implemented | autocapture_nx/capture/pipeline.py |
| I026 | Phase 3 | Default to SQLCipher for metadata when available | implemented | plugins/builtin/storage_sqlcipher/plugin.py<br>config/default.json |
| I027 | Phase 3 | Add DB indexes on ts_utc, record_type, run_id | implemented | plugins/builtin/storage_sqlcipher/plugin.py |
| I028 | Phase 3 | Store media in binary encrypted format (not base64 JSON) | implemented | plugins/builtin/storage_encrypted/plugin.py<br>plugins/builtin/storage_sqlcipher/plugin.py |
| I029 | Phase 3 | Stream encryption (avoid whole-segment in memory) | implemented | plugins/builtin/storage_encrypted/plugin.py<br>autocapture_nx/capture/pipeline.py |
| I030 | Phase 3 | Immutability/versioning in stores (put_new vs put_replace) | implemented | plugins/builtin/storage_encrypted/plugin.py<br>plugins/builtin/storage_sqlcipher/plugin.py<br>autocapture_nx/kernel/metadata_store.py |
| I031 | Phase 3 | Make record ID encoding reversible (no lossy mapping) | implemented | autocapture_nx/kernel/ids.py<br>autocapture_nx/processing/idle.py<br>autocapture_nx/kernel/query.py<br>autocapture_nx/capture/pipeline.py |
| I032 | Phase 3 | Shard media/metadata directories by date/run | implemented | plugins/builtin/storage_encrypted/plugin.py |
| I033 | Phase 3 | Add per-run storage manifest records | implemented | autocapture_nx/kernel/loader.py |
| I034 | Phase 3 | Configurable fsync policy (critical vs bulk) | implemented | plugins/builtin/storage_encrypted/plugin.py<br>plugins/builtin/journal_basic/plugin.py<br>plugins/builtin/ledger_basic/plugin.py |
| I035 | Phase 4 | Replace full-scan query with tiered indexed retrieval | implemented | plugins/builtin/retrieval_basic/plugin.py<br>autocapture/indexing/lexical.py<br>autocapture/indexing/vector.py |
| I036 | Phase 4 | Deterministic retrieval ordering (stable sort keys) | implemented | plugins/builtin/retrieval_basic/plugin.py |
| I037 | Phase 4 | Candidate-first extraction (retrieve then extract) | implemented | autocapture_nx/kernel/query.py |
| I038 | Phase 4 | Derived artifact records for OCR/VLM outputs | implemented | autocapture_nx/kernel/derived_records.py<br>autocapture_nx/kernel/query.py<br>autocapture_nx/processing/idle.py |
| I039 | Phase 4 | Ledger query executions (inputs/outputs) | implemented | autocapture_nx/kernel/query.py<br>autocapture_nx/kernel/event_builder.py |
| I040 | Phase 4 | Ledger extraction operations (inputs/outputs) | implemented | autocapture_nx/kernel/query.py |
| I041 | Phase 4 | Citations point to immutable evidence IDs + spans | implemented | contracts/citation.schema.json<br>plugins/builtin/citation_basic/plugin.py<br>autocapture_nx/kernel/query.py |
| I042 | Phase 4 | Citation resolver validates hashes/anchors/spans | implemented | plugins/builtin/citation_basic/plugin.py |
| I043 | Phase 4 | Fail closed if citations do not resolve | implemented | plugins/builtin/answer_basic/plugin.py |
| I044 | Phase 5 | Real scheduler plugin gates heavy work on user activity | implemented | autocapture/runtime/conductor.py<br>autocapture/runtime/scheduler.py<br>autocapture/runtime/governor.py<br>autocapture/runtime/budgets.py<br>plugins/builtin/runtime_scheduler/plugin.py<br>plugins/builtin/runtime_governor/plugin.py |
| I045 | Phase 5 | Input tracker exposes activity signals (not only journal) | implemented | plugins/builtin/input_windows/plugin.py |
| I046 | Phase 5 | Capture emits telemetry (queues, drops, lag, CPU) | implemented | autocapture_nx/capture/pipeline.py<br>autocapture_nx/kernel/telemetry.py<br>autocapture/web/routes/metrics.py |
| I047 | Phase 5 | Governor outputs feed backpressure and job admission | implemented | autocapture_nx/capture/pipeline.py<br>autocapture/runtime/conductor.py |
| I048 | Phase 5 | Immediate ramp down on user input (cancel/deprioritize heavy jobs) | implemented | autocapture/runtime/governor.py<br>autocapture/runtime/scheduler.py<br>autocapture/runtime/conductor.py<br>autocapture_nx/processing/idle.py |
| I049 | Phase 6 | Egress gateway must be subprocess-hosted; kernel network-denied | implemented | autocapture_nx/kernel/loader.py<br>autocapture_nx/plugin_system/runtime.py<br>autocapture_nx/plugin_system/host_runner.py<br>autocapture_nx/plugin_system/registry.py<br>config/default.json |
| I050 | Phase 6 | Minimize inproc_allowlist; prefer subprocess hosting | implemented | config/default.json<br>autocapture_nx/plugin_system/registry.py |
| I051 | Phase 6 | Capability bridging for subprocess plugins (real capability plumbing) | implemented | autocapture_nx/plugin_system/runtime.py<br>autocapture_nx/plugin_system/host_runner.py<br>autocapture_nx/plugin_system/registry.py |
| I052 | Phase 6 | Enforce least privilege per plugin manifest | implemented | contracts/plugin_manifest.schema.json<br>plugins/builtin/*/plugin.json<br>autocapture_nx/plugin_system/registry.py |
| I053 | Phase 6 | Enforce filesystem permission policy declared by plugins | implemented | autocapture_nx/plugin_system/registry.py<br>autocapture_nx/plugin_system/host_runner.py<br>autocapture_nx/plugin_system/runtime.py |
| I054 | Phase 6 | Strengthen Windows job object restrictions (limits) | implemented | autocapture_nx/windows/win_sandbox.py<br>autocapture_nx/plugin_system/host.py<br>config/default.json |
| I055 | Phase 6 | Sanitize subprocess env; pin caches; disable proxies | implemented | autocapture_nx/plugin_system/host.py |
| I056 | Phase 6 | Plugin RPC timeouts and watchdogs | implemented | autocapture_nx/plugin_system/host.py |
| I057 | Phase 6 | Max message size limits in plugin RPC protocol | implemented | autocapture_nx/plugin_system/host.py<br>autocapture_nx/plugin_system/host_runner.py |
| I058 | Phase 6 | Harden hashing against symlinks / filesystem nondeterminism | implemented | autocapture_nx/kernel/hashing.py |
| I059 | Phase 6 | Secure vault file permissions (Windows ACLs) | implemented | autocapture_nx/windows/acl.py<br>autocapture_nx/kernel/crypto.py<br>autocapture_nx/kernel/keyring.py |
| I060 | Phase 6 | Separate keys by purpose (metadata/media/tokenization/anchor) | implemented | autocapture_nx/kernel/keyring.py<br>autocapture/storage/blob_store.py<br>autocapture/storage/database.py<br>autocapture/storage/keys.py<br>autocapture/storage/sqlcipher.py<br>plugins/builtin/anchor_basic/plugin.py<br>plugins/builtin/egress_sanitizer/plugin.py<br>plugins/builtin/storage_encrypted/plugin.py |
| I061 | Phase 6 | Anchor signing (HMAC/signature) with separate key domain | implemented | plugins/builtin/anchor_basic/plugin.py<br>autocapture_nx/kernel/keyring.py<br>autocapture/pillars/citable.py |
| I062 | Phase 6 | Add verify commands (ledger/anchors/evidence) | implemented | autocapture_nx/cli.py<br>autocapture/pillars/citable.py<br>autocapture/ux/facade.py<br>autocapture/web/routes/verify.py<br>plugins/builtin/ledger_basic/plugin.py<br>plugins/builtin/journal_basic/plugin.py |
| I063 | Phase 6 | Audit security events in ledger (key rotations, lock updates, config) | implemented | autocapture_nx/kernel/key_rotation.py<br>autocapture_nx/kernel/loader.py<br>plugins/builtin/ledger_basic/plugin.py |
| I064 | Phase 6 | Dependency pinning + hash checking (supply chain) | implemented | autocapture_nx/kernel/loader.py<br>requirements.lock.json |
| I065 | Phase 4 | Define canonical evidence model (EvidenceObject) | implemented | contracts/evidence.schema.json<br>autocapture_nx/kernel/metadata_store.py |
| I066 | Phase 4 | Hash everything that matters (media/metadata/derived) | implemented | autocapture_nx/capture/pipeline.py<br>autocapture_nx/kernel/derived_records.py<br>plugins/builtin/window_metadata_windows/plugin.py |
| I067 | Phase 4 | Ledger every state transition | implemented | autocapture_nx/capture/pipeline.py |
| I068 | Phase 4 | Anchor on schedule (N entries or M minutes) | implemented | autocapture_nx/kernel/event_builder.py<br>config/default.json |
| I069 | Phase 4 | Immutable per-run manifest (config+locks+versions) | implemented | autocapture_nx/kernel/loader.py |
| I070 | Phase 4 | Citation objects carry verifiable pointers | implemented | contracts/citation.schema.json<br>plugins/builtin/citation_basic/plugin.py |
| I071 | Phase 4 | Citation resolver CLI/API | implemented | autocapture_nx/cli.py<br>autocapture/web/routes/citations.py<br>autocapture/ux/facade.py |
| I072 | Phase 4 | Metadata immutable by default; derived never overwrites | implemented | autocapture_nx/kernel/metadata_store.py |
| I073 | Phase 4 | Persist derivation graphs (parent->child links) | implemented | autocapture_nx/kernel/derived_records.py<br>autocapture_nx/kernel/query.py |
| I074 | Phase 4 | Record model identity for ML outputs | implemented | autocapture_nx/kernel/derived_records.py |
| I075 | Phase 4 | Deterministic text normalization before hashing | implemented | autocapture/core/hashing.py<br>autocapture_nx/kernel/derived_records.py |
| I076 | Phase 4 | Proof bundles export (evidence + ledger slice + anchors) | implemented | autocapture_nx/kernel/proof_bundle.py<br>autocapture_nx/cli.py<br>autocapture/ux/facade.py |
| I077 | Phase 4 | Replay mode validates citations without model calls | implemented | autocapture_nx/kernel/replay.py<br>autocapture_nx/cli.py |
| I078 | Phase 7 | FastAPI UX facade as canonical interface | implemented | autocapture_nx/ux/facade.py<br>autocapture/web/api.py<br>autocapture/web/routes |
| I079 | Phase 7 | CLI parity: CLI calls shared UX facade functions | implemented | autocapture_nx/cli.py<br>autocapture_nx/ux/facade.py |
| I080 | Phase 7 | Web Console UI (status/timeline/query/proof/plugins/keys) | implemented | autocapture/web/ui<br>autocapture/web/api.py |
| I081 | Phase 7 | Alerts panel driven by journal events | implemented | autocapture_nx/kernel/alerts.py<br>autocapture/web/routes/alerts.py<br>autocapture/web/ui |
| I082 | Phase 7 | Local-only auth boundary (bind localhost + token) | implemented | autocapture/web/auth.py<br>autocapture_nx/kernel/auth.py<br>config/default.json |
| I083 | Phase 7 | Websocket for live telemetry | implemented | autocapture/web/routes/telemetry.py<br>autocapture/web/ui |
| I084 | Phase 0 | Split heavy ML dependencies into optional extras | implemented | pyproject.toml<br>plugins/builtin/*/plugin.json<br>tests/test_optional_deps_imports.py<br>tests/test_optional_dependency_imports.py |
| I085 | Phase 0 | Make resource paths package-safe (no CWD dependence) | implemented | autocapture_nx/kernel/paths.py<br>tests/test_paths_package_safe.py<br>tests/test_packaged_resources.py |
| I086 | Phase 0 | Use OS-appropriate default data/config dirs (platformdirs) | implemented | autocapture_nx/kernel/paths.py<br>tests/test_platform_paths.py<br>config/default.json |
| I087 | Phase 0 | Package builtin plugins as package data | implemented | pyproject.toml<br>tests/test_packaged_resources.py<br>tests/test_plugin_package_data.py |
| I088 | Phase 0 | Add reproducible dependency lockfile (hash-locked) | implemented | requirements.lock.json<br>tools/generate_dep_lock.py<br>tools/gate_deps_lock.py |
| I089 | Phase 0 | Add canonical-json safety tests for journal/ledger payloads | implemented | tests/test_canonical_payloads.py<br>tests/test_canonical_json.py<br>tools/gate_canon.py |
| I090 | Phase 0 | Add concurrency tests for ledger/journal append correctness | implemented | tests/test_ledger_journal_concurrency.py<br>tools/gate_concurrency.py |
| I091 | Phase 0 | Add golden chain test: ledger verify + anchor verify | implemented | tests/test_ledger_anchor_golden.py<br>tools/gate_ledger.py |
| I092 | Phase 0 | Add performance regression tests (capture latency/memory/query latency) | implemented | tools/gate_perf.py<br>tools/run_all_tests.py |
| I093 | Phase 0 | Add security regression tests (DPAPI fail-closed, network guard, no raw egress) | implemented | tools/gate_security.py<br>tests/test_network_guard.py<br>tests/test_plugin_network_block.py<br>tests/test_encrypted_store_fail_loud.py<br>tests/test_policy_gate.py |
| I094 | Phase 0 | Static analysis: ruff + typing + vuln scan | implemented | tools/gate_static.py<br>tools/gate_vuln.py<br>pyproject.toml<br>tools/run_all_tests.py |
| I095 | Phase 0 | Doctor validates locks, storage, anchors, and network policy | implemented | autocapture_nx/kernel/loader.py<br>tools/gate_doctor.py<br>tests/test_doctor_locks.py<br>tests/test_doctor_report_schema.py |
| I096 | Phase 1 | Fail loud on decrypt errors when encryption_required | implemented | autocapture_nx/kernel/keyring.py<br>plugins/builtin/storage_encrypted/plugin.py<br>plugins/builtin/storage_sqlcipher/plugin.py<br>tests/test_encrypted_store_fail_loud.py |
| I097 | Phase 1 | Add record type fields everywhere | implemented | autocapture_nx/kernel/metadata_store.py<br>plugins/builtin/capture_windows/plugin.py<br>plugins/builtin/window_metadata_windows/plugin.py<br>tests/test_metadata_record_type.py |
| I098 | Phase 1 | Add unified EventBuilder helper | implemented | autocapture_nx/kernel/event_builder.py<br>autocapture_nx/kernel/loader.py<br>plugins/builtin/capture_windows/plugin.py<br>plugins/builtin/audio_windows/plugin.py<br>tests/test_event_builder.py |
| I099 | Phase 1 | Stamp every journal event with run_id | implemented | plugins/builtin/journal_basic/plugin.py<br>autocapture_nx/kernel/event_builder.py<br>tests/test_journal_run_id.py |
| I100 | Phase 1 | Cache policy snapshot hashing per run | implemented | autocapture_nx/kernel/event_builder.py<br>tests/test_event_builder.py |
| I101 | Phase 3 | Add content_hash to metadata for every media put | implemented | autocapture_nx/capture/pipeline.py<br>plugins/builtin/audio_windows/plugin.py<br>plugins/builtin/input_windows/plugin.py |
| I102 | Phase 3 | Track partial failures explicitly in journal/ledger | implemented | autocapture_nx/capture/pipeline.py |
| I103 | Phase 3 | Add segment sealing ledger entry after successful write | implemented | autocapture_nx/capture/pipeline.py |
| I104 | Phase 3 | Add startup recovery scanner to reconcile stores | implemented | autocapture_nx/kernel/loader.py |
| I105 | Phase 2 | If keeping zips, use ZIP_STORED for JPEG frames | implemented | autocapture_nx/capture/pipeline.py |
| I106 | Phase 2 | If keeping zips, stream ZipFile writes to a real file | implemented | autocapture_nx/capture/pipeline.py |
| I107 | Phase 2 | Batch input events to reduce write overhead | implemented | plugins/builtin/input_windows/plugin.py<br>plugins/builtin/journal_basic/plugin.py |
| I108 | Phase 3 | Add compact binary input log (derived) + JSON summary | implemented | plugins/builtin/input_windows/plugin.py |
| I109 | Phase 2 | Add WASAPI loopback option for system audio capture | implemented | plugins/builtin/audio_windows/plugin.py |
| I110 | Phase 2 | Store audio as PCM/FLAC/Opus derived artifact | implemented | plugins/builtin/audio_windows/plugin.py |
| I111 | Phase 2 | Normalize active window process paths (device -> drive paths) | implemented | autocapture_nx/windows/win_window.py<br>plugins/builtin/window_metadata_windows/plugin.py |
| I112 | Phase 2 | Capture window.rect and monitor mapping | implemented | autocapture_nx/windows/win_window.py<br>plugins/builtin/window_metadata_windows/plugin.py |
| I113 | Phase 2 | Optional cursor position+shape capture | implemented | autocapture_nx/windows/win_cursor.py<br>plugins/builtin/cursor_windows/plugin.py<br>autocapture_nx/capture/pipeline.py |
| I114 | Phase 8 | Clipboard capture plugin (local-only, append-only) | implemented | plugins/builtin/clipboard_windows |
| I115 | Phase 8 | File activity capture plugin (USN journal / watcher) | implemented | plugins/builtin/file_activity_windows |
| I116 | Phase 5 | Model execution budgets per idle window | implemented | autocapture/runtime/governor.py<br>autocapture/runtime/scheduler.py<br>autocapture/runtime/budgets.py<br>autocapture/runtime/conductor.py<br>autocapture_nx/processing/idle.py |
| I117 | Phase 5 | Preemption/chunking for long jobs | implemented | autocapture/runtime/conductor.py<br>autocapture_nx/processing/idle.py<br>autocapture/research/runner.py |
| I118 | Phase 4 | Index versioning for retrieval reproducibility | implemented | autocapture/indexing/manifest.py<br>autocapture/indexing/lexical.py<br>autocapture/indexing/vector.py<br>plugins/builtin/retrieval_basic/plugin.py |
| I119 | Phase 6 | Persist entity-tokenizer key id/version; version tokenization | implemented | plugins/builtin/egress_sanitizer/plugin.py<br>plugins/builtin/storage_sqlcipher/plugin.py<br>plugins/builtin/storage_encrypted/plugin.py<br>plugins/builtin/storage_memory/plugin.py |
| I120 | Phase 6 | Ledger sanitized egress packets (hash + schema version) | implemented | plugins/builtin/egress_gateway/plugin.py<br>autocapture_nx/kernel/egress_approvals.py |
| I121 | Phase 7 | Egress approval workflow in UI | implemented | autocapture_nx/kernel/egress_approvals.py<br>autocapture/web/routes/egress.py<br>autocapture/web/ui |
| I122 | Phase 8 | Plugin hot-reload with hash verification and safe swap | implemented | autocapture_nx/plugin_system/registry.py<br>autocapture_nx/kernel/loader.py |
| I123 | Phase 1 | Write kernel boot ledger entry system.start | implemented | autocapture_nx/kernel/loader.py<br>tests/test_run_state_entries.py |
| I124 | Phase 1 | Write kernel shutdown ledger entry system.stop | implemented | autocapture_nx/kernel/loader.py<br>tests/test_run_state_entries.py |
| I125 | Phase 1 | Write crash ledger entry on next startup | implemented | autocapture_nx/kernel/loader.py<br>tests/test_run_state_entries.py |
| I126 | Phase 0 | Make sha256_directory path sorting deterministic across OSes | implemented | autocapture_nx/kernel/hashing.py<br>tests/test_directory_hashing.py<br>tests/test_hashing_directory_deterministic.py |
| I127 | Phase 4 | Record python/OS/package versions into run manifest | implemented | autocapture_nx/kernel/loader.py |
| I128 | Phase 3 | Tooling to migrate data_dir safely (copy+verify, no delete) | implemented | autocapture/storage/migrate.py<br>autocapture_nx/cli.py |
| I129 | Phase 3 | Disk usage forecasting (days remaining) + alerts | implemented | autocapture/storage/pressure.py<br>autocapture/storage/forecast.py<br>autocapture/runtime/conductor.py<br>autocapture_nx/kernel/loader.py<br>autocapture_nx/cli.py |
| I130 | Phase 3 | Storage compaction for derived artifacts only | implemented | autocapture/storage/compaction.py<br>autocapture_nx/kernel/metadata_store.py<br>autocapture_nx/cli.py |
