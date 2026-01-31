# ASSUMPTIONS (Testable/Configurable)

1) Desktop Duplication + NVENC capture backend is not implemented; Windows capture uses mss + JPEG fallback.
   - Test coverage: `tests/test_windows_plugins.py` (Windows only) and `tests/test_backpressure.py`.
   - Mitigation: implement Desktop Duplication + NVENC pipeline and add Windows integration benchmarks.

2) Root keys are stored in a DPAPI-protected keyring file on Windows; non-Windows uses raw files.
   - Test coverage: `tests/test_storage_encrypted.py`, `tests/test_key_rotation.py`.
   - Mitigation: integrate Windows Credential Manager or hardware-backed vault.

3) Key rotation is user-invoked via `autocapture keys rotate` and assumed to run during IDLE_DRAIN or explicit user intent.
   - Test coverage: `tests/test_key_rotation.py`.
   - Mitigation: add scheduler gate enforcing runtime mode and background rekey jobs.

4) Name detection uses heuristic regex (capitalized multi-word sequences).
   - Test coverage: `tests/test_sanitizer.py`.
   - Mitigation: upgrade recognizer stack to local NER model.

5) Anchor store is a separate path by default but remains on the same machine unless configured otherwise.
   - Test coverage: `tests/test_anchor.py` verifies anchor records are written.
   - Mitigation: configure a second trust domain (registry/credential manager/remote drive).

6) Plugin sandboxing is Python-level (network guard) plus a Windows JobObject; no full OS sandbox yet.
   - Test coverage: `tests/test_plugin_network_block.py` enforces socket denial via guard.
   - Mitigation: add OS sandbox / process isolation for plugin hosts.

7) Windows capture/audio/input plugins rely on optional third-party dependencies (mss, Pillow, pynput, sounddevice, pytesseract, transformers, sentence-transformers).
   - Test coverage: `tests/test_windows_plugins.py` (Windows only).
   - Mitigation: pin dependencies and run Windows integration tests.

8) SQLCipher metadata store requires `pysqlcipher3` and is not exercised in non-Windows tests.
   - Test coverage: `tests/test_sqlcipher_store.py` tolerates missing deps; Windows integration tests required.
   - Mitigation: run Windows DB integration suite after installing SQLCipher.

9) Subprocess plugin host is implemented but most built-ins are allowlisted in-proc to preserve capability access.
   - Test coverage: `tests/test_plugin_loader.py` ensures allowlist enforcement.
   - Mitigation: expand RPC bridging so more plugins can run out-of-proc.

10) Runtime governor only selects modes; worker suspension and VRAM release are not yet enforced.
   - Test coverage: `tests/test_time_parser.py` and `tests/test_backpressure.py` cover mode signals indirectly.
   - Mitigation: implement worker group suspension + GPU release policies with integration tests.

11) UI plugins (loopback web/overlay) are not implemented.
   - Test coverage: none.
   - Mitigation: add UI plugins with CSRF + origin pinning tests.

12) Retrieval uses lexical matching over stored spans; vector indices and reranker integration are not wired into retrieval.
   - Test coverage: `tests/test_retrieval.py`.
   - Mitigation: implement vector index builder + reranker integration with golden query suite.

13) Windows permission matrix and degraded-mode policy checks are not implemented.
   - Test coverage: none.
   - Mitigation: add doctor checks and Windows integration tests for permission failures.
