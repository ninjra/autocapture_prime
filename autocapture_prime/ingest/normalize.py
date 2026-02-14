from __future__ import annotations


def qpc_to_relative_seconds(qpc_ticks: int, start_qpc_ticks: int, qpc_frequency_hz: int) -> float:
    if qpc_frequency_hz <= 0:
        return 0.0
    return float(qpc_ticks - start_qpc_ticks) / float(qpc_frequency_hz)
