from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from autocapture_nx.cli import build_parser
from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.export_chatgpt import run_export_pass


@pytest.fixture(autouse=True)
def _set_export_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KERNEL_AUTOCAPTURE_EXPORT_ROOT", str(tmp_path / "exports"))


def _write_journal(path: Path, *, segment_id: str, ts_utc: str, frame_count: int = 3) -> None:
    payload = {
        "schema_version": 1,
        "record_type": "evidence.capture.segment",
        "run_id": "run_test",
        "segment_id": segment_id,
        "ts_utc": ts_utc,
        "ts_start_utc": ts_utc,
        "frame_count": frame_count,
    }
    line = {
        "schema_version": 1,
        "event_id": segment_id,
        "sequence": 1,
        "ts_utc": ts_utc,
        "tzid": "UTC",
        "offset_minutes": 0,
        "event_type": "capture.segment",
        "payload": payload,
        "run_id": "run_test",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")


def _zip_frames() -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("frame_0.jpg", b"f0")
        zf.writestr("frame_1.jpg", b"f1")
        zf.writestr("frame_2.jpg", b"f2")
    return buf.getvalue()


class _FakeMetadataStore:
    def __init__(self, rows: dict[str, dict] | None = None) -> None:
        self._rows = dict(rows or {})

    def keys(self) -> list[str]:
        return sorted(self._rows.keys())

    def get(self, key: str, default=None):
        return self._rows.get(key, default)

    def put_replace(self, key: str, value: dict) -> None:
        self._rows[key] = dict(value)

    def put(self, key: str, value: dict) -> None:
        self._rows[key] = dict(value)


class _FakeMediaStore:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self._blobs = dict(blobs)

    def get(self, key: str, default=None):
        return self._blobs.get(key, default)


class _FakeOcr:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract(self, _image_bytes: bytes) -> dict:
        return {"text": self._text}


class _LeakPassSanitizer:
    def sanitize_text(self, text: str, scope: str = "default") -> dict:
        return {"text": text, "glossary": [{"token": "tok1", "kind": "NAME"}], "tokens": {"tok1": {"value": "a", "kind": "NAME"}}}

    def leak_check(self, _payload: dict) -> bool:
        return True


class _LeakFailSanitizer:
    def sanitize_text(self, _text: str, scope: str = "default") -> dict:
        return {
            "text": "sanitized",
            "glossary": [{"token": "tok2", "kind": "EMAIL"}],
            "tokens": {"tok2": {"value": "sensitive@example.com", "kind": "EMAIL"}},
        }

    def leak_check(self, _payload: dict) -> bool:
        return False


class _FakeSystem:
    def __init__(self, config: dict, caps: dict[str, object]) -> None:
        self.config = config
        self._caps = dict(caps)

    def get(self, name: str):
        return self._caps.get(name)

    def has(self, name: str) -> bool:
        return name in self._caps and self._caps.get(name) is not None


def _window_meta(ts_utc: str, title: str = "ChatGPT - Microsoft Edge") -> dict:
    return {
        "schema_version": 1,
        "record_type": "evidence.window.meta",
        "ts_utc": ts_utc,
        "run_id": "run_test",
        "window": {
            "title": title,
            "process_path": r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        },
    }


def test_export_chatgpt_hash_chain_and_schema(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    journal = data_dir / "journal.ndjson"
    _write_journal(journal, segment_id="seg1", ts_utc="2026-02-17T20:00:05+00:00")
    metadata = _FakeMetadataStore({"run_test/window/0": _window_meta("2026-02-17T20:00:00+00:00")})
    media = _FakeMediaStore({"seg1": _zip_frames()})
    system = _FakeSystem(
        {"storage": {"data_dir": str(data_dir)}},
        {
            "storage.metadata": metadata,
            "storage.media": media,
            "ocr.engine": _FakeOcr("ChatGPT transcript text long enough to pass threshold and remain deterministic."),
            "privacy.egress_sanitizer": _LeakPassSanitizer(),
        },
    )

    result = run_export_pass(system, max_segments=5, since_ts=None)
    assert result["ok"] is True
    assert int(result["segments_exported"]) == 1
    assert int(result["lines_appended"]) >= 1

    export_path = Path(result["export_path"])
    assert export_path.exists()
    lines = [json.loads(line) for line in export_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    prev_hash = None
    for row in lines:
        for key in ("schema_version", "entry_id", "ts_utc", "source", "segment_id", "frame_name", "text", "glossary", "prev_hash", "entry_hash"):
            assert key in row
        assert row["prev_hash"] == prev_hash
        payload = {k: v for k, v in row.items() if k != "entry_hash"}
        expected = hashlib.sha256((dumps(payload) + (prev_hash or "")).encode("utf-8")).hexdigest()
        assert row["entry_hash"] == expected
        prev_hash = row["entry_hash"]

    marker = metadata.get("export.chatgpt.seg1")
    assert isinstance(marker, dict)
    assert marker.get("record_type") == "derived.export.chatgpt.segment"


def test_export_chatgpt_leak_check_failure_empties_text(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_journal(data_dir / "journal.ndjson", segment_id="seg2", ts_utc="2026-02-17T20:10:05+00:00")
    metadata = _FakeMetadataStore({"run_test/window/0": _window_meta("2026-02-17T20:10:00+00:00")})
    system = _FakeSystem(
        {"storage": {"data_dir": str(data_dir)}},
        {
            "storage.metadata": metadata,
            "storage.media": _FakeMediaStore({"seg2": _zip_frames()}),
            "ocr.engine": _FakeOcr("ChatGPT transcript text long enough to pass threshold and leak check path."),
            "privacy.egress_sanitizer": _LeakFailSanitizer(),
        },
    )

    result = run_export_pass(system)
    assert result["ok"] is True
    lines = [
        json.loads(line)
        for line in Path(result["export_path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines
    assert lines[0]["text"] == ""
    assert lines[0]["export_notice"] == "leak_check_failed"


def test_export_chatgpt_missing_ocr_is_nonfatal(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_journal(data_dir / "journal.ndjson", segment_id="seg3", ts_utc="2026-02-17T20:20:05+00:00")
    metadata = _FakeMetadataStore({"run_test/window/0": _window_meta("2026-02-17T20:20:00+00:00")})
    system = _FakeSystem(
        {"storage": {"data_dir": str(data_dir)}},
        {
            "storage.metadata": metadata,
            "storage.media": _FakeMediaStore({"seg3": _zip_frames()}),
            "privacy.egress_sanitizer": _LeakPassSanitizer(),
        },
    )

    result = run_export_pass(system)
    assert result["ok"] is True
    assert int(result["segments_exported"]) == 0
    assert int(result["lines_appended"]) == 0
    assert int(result["segments_skipped_no_text"]) >= 1


def test_export_chatgpt_idempotent_segment_marker(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _write_journal(data_dir / "journal.ndjson", segment_id="seg4", ts_utc="2026-02-17T20:30:05+00:00")
    metadata = _FakeMetadataStore({"run_test/window/0": _window_meta("2026-02-17T20:30:00+00:00")})
    system = _FakeSystem(
        {"storage": {"data_dir": str(data_dir)}},
        {
            "storage.metadata": metadata,
            "storage.media": _FakeMediaStore({"seg4": _zip_frames()}),
            "ocr.engine": _FakeOcr("ChatGPT transcript text long enough to pass threshold and write once."),
            "privacy.egress_sanitizer": _LeakPassSanitizer(),
        },
    )

    first = run_export_pass(system)
    second = run_export_pass(system)
    assert int(first["segments_exported"]) == 1
    assert int(second["segments_exported"]) == 0
    assert int(second["segments_skipped_already_exported"]) >= 1


def test_cli_parser_has_export_chatgpt_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["export", "chatgpt", "--max-segments", "10", "--since-ts", "2026-02-17T00:00:00+00:00"])
    assert args.command == "export"
    assert args.export_cmd == "chatgpt"
    assert int(args.max_segments) == 10
    assert str(args.since_ts) == "2026-02-17T00:00:00+00:00"
