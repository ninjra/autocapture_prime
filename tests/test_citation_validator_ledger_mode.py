from __future__ import annotations

import json
import os
import tempfile

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.citation_basic.plugin import CitationValidator


def _write_corrupt_ledger(path: str) -> str:
    entry = {
        "record_type": "ledger.entry",
        "schema_version": 1,
        "entry_id": "run/ledger/0",
        "ts_utc": "2026-02-22T00:00:00Z",
        "stage": "query.execute",
        "inputs": [],
        "outputs": [],
        "policy_snapshot_hash": "policy",
        "payload": {"event": "query.execute"},
        "prev_hash": None,
        # Deliberately incorrect hash-chain value for strict verification.
        "entry_hash": "deadbeef",
    }
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, separators=(",", ":"), sort_keys=True) + "\n")
    return str(entry["entry_hash"])


def test_ledger_verification_is_lenient_by_default_on_legacy_chain() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        expected = _write_corrupt_ledger(os.path.join(tmp, "ledger.ndjson"))
        ctx = PluginContext(config={"storage": {"data_dir": tmp}}, get_capability=lambda _n: None, logger=lambda _m: None)
        validator = CitationValidator("cit", ctx)
        assert validator._verify_ledger(expected) is True  # noqa: SLF001


def test_ledger_verification_strict_mode_rejects_legacy_chain() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        expected = _write_corrupt_ledger(os.path.join(tmp, "ledger.ndjson"))
        prev = os.environ.get("AUTOCAPTURE_CITATION_REQUIRE_STRICT_LEDGER")
        os.environ["AUTOCAPTURE_CITATION_REQUIRE_STRICT_LEDGER"] = "1"
        try:
            ctx = PluginContext(config={"storage": {"data_dir": tmp}}, get_capability=lambda _n: None, logger=lambda _m: None)
            validator = CitationValidator("cit", ctx)
            assert validator._verify_ledger(expected) is False  # noqa: SLF001
        finally:
            if prev is None:
                os.environ.pop("AUTOCAPTURE_CITATION_REQUIRE_STRICT_LEDGER", None)
            else:
                os.environ["AUTOCAPTURE_CITATION_REQUIRE_STRICT_LEDGER"] = prev


def test_lenient_mode_accepts_non_head_hash_if_present_in_ledger() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ledger.ndjson")
        rows = [
            {
                "record_type": "ledger.entry",
                "schema_version": 1,
                "entry_id": "run/ledger/0",
                "ts_utc": "2026-02-22T00:00:00Z",
                "stage": "query.execute",
                "inputs": [],
                "outputs": [],
                "policy_snapshot_hash": "policy",
                "payload": {"event": "query.execute"},
                "prev_hash": None,
                "entry_hash": "hash_a",
            },
            {
                "record_type": "ledger.entry",
                "schema_version": 1,
                "entry_id": "run/ledger/1",
                "ts_utc": "2026-02-22T00:00:01Z",
                "stage": "query.execute",
                "inputs": [],
                "outputs": [],
                "policy_snapshot_hash": "policy",
                "payload": {"event": "query.execute"},
                "prev_hash": "hash_a",
                "entry_hash": "hash_b",
            },
        ]
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
        ctx = PluginContext(config={"storage": {"data_dir": tmp}}, get_capability=lambda _n: None, logger=lambda _m: None)
        validator = CitationValidator("cit", ctx)
        assert validator._verify_ledger("hash_a") is True  # noqa: SLF001
