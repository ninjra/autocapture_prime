from datetime import datetime, timezone

import pytest


def test_utc_iso_z_formatting():
    from autocapture_nx.kernel.timebase import utc_iso_z

    dt = datetime(2026, 2, 8, 12, 34, 56, tzinfo=timezone.utc)
    assert utc_iso_z(dt).endswith("Z")
    assert "+00:00" not in utc_iso_z(dt)


def test_tz_offset_minutes_matches_zoneinfo_when_available():
    from autocapture_nx.kernel.timebase import ZoneInfo, tz_offset_minutes

    if ZoneInfo is None:
        pytest.skip("zoneinfo unavailable")

    tzid = "America/Denver"
    before = datetime(2026, 3, 8, 8, 59, 0, tzinfo=timezone.utc)  # before DST switch locally
    after = datetime(2026, 3, 8, 10, 1, 0, tzinfo=timezone.utc)  # after DST switch locally

    offset_before = tz_offset_minutes(tzid, at_utc=before)
    offset_after = tz_offset_minutes(tzid, at_utc=after)

    assert offset_before in (-420, -360)
    assert offset_after in (-420, -360)
    assert offset_before != offset_after


def test_journal_writer_autofills_offset_minutes(tmp_path):
    from plugins.builtin.journal_basic.plugin import JournalWriter
    from autocapture_nx.plugin_system.api import PluginContext

    cfg = {
        "storage": {"data_dir": str(tmp_path)},
        "runtime": {"run_id": "run-test", "timezone": "UTC"},
    }
    ctx = PluginContext(config=cfg, get_capability=lambda _n: None, logger=lambda _m: None)
    writer = JournalWriter("builtin.journal.basic", ctx)

    entry = {
        "schema_version": 1,
        "event_id": "",
        "sequence": None,
        "ts_utc": "",
        "tzid": "",
        "offset_minutes": None,
        "event_type": "test.event",
        "payload": {"x": 1},
        "run_id": "",
    }
    writer.append(entry)
    assert isinstance(entry["offset_minutes"], int)
    assert entry["offset_minutes"] == 0
    assert str(entry["ts_utc"]).endswith("Z")

