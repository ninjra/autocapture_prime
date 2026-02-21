from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, Path(path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_bench_emits_sla_and_timing_rows() -> None:
    mod = _load_module("tools/bench_batch_knobs_synthetic.py", "bench_batch_knobs_synthetic_tool")
    out = mod.run_bench(workers=[1, 2], pending=200, completed_per_step=5, loops=5, repeats=3)
    assert bool(out.get("ok", False))
    rows = out.get("scenarios", [])
    assert isinstance(rows, list) and len(rows) == 2
    for row in rows:
        assert int(row.get("workers") or 0) >= 1
        sla = row.get("sla", {})
        assert isinstance(sla, dict)
        assert "throughput_records_per_s" in sla
        assert "retention_risk" in sla
        assert float(row.get("eval_median_us") or 0.0) >= 0.0
