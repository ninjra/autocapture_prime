from __future__ import annotations

import time

from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.input_windows.plugin import InputTrackerWindows


def test_activity_signal_uses_last_input_idle_seconds() -> None:
    cfg = {"runtime": {"active_window_s": 300, "activity": {"assume_idle_when_missing": False}}}
    ctx = PluginContext(config=cfg, get_capability=lambda _name: None, logger=lambda _msg: None)
    plugin = InputTrackerWindows("builtin.input.windows", ctx)

    # Disable power/screensaver probes for deterministic CI behavior.
    plugin._display_enabled = False  # type: ignore[attr-defined]
    plugin._screensaver_enabled = False  # type: ignore[attr-defined]

    now = time.time()
    plugin._last_event_ts = now - 600  # type: ignore[attr-defined]
    signal = plugin.activity_signal()
    assert signal["idle_seconds"] >= 599
    assert signal["user_active"] is False

    plugin._last_event_ts = now - 10  # type: ignore[attr-defined]
    signal2 = plugin.activity_signal()
    assert 0 <= signal2["idle_seconds"] <= 15
    assert signal2["user_active"] is True

