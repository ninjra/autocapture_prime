from __future__ import annotations

from autocapture_nx.windows.win_idle import _TickSnapshot, _elapsed_ms


def test_elapsed_ms_no_wrap() -> None:
    snap = _TickSnapshot(now_ms=2000, last_input_ms=1500, wrap_32bit=False)
    assert _elapsed_ms(snap) == 500


def test_elapsed_ms_wrap_32bit() -> None:
    # Simulate 32-bit tick wrap: last near max, now small.
    snap = _TickSnapshot(now_ms=50, last_input_ms=0xFFFFFFF0, wrap_32bit=True)
    assert _elapsed_ms(snap) == ((50 - 0xFFFFFFF0) & 0xFFFFFFFF)

