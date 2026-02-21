#!/usr/bin/env python3
from __future__ import annotations

import argparse
from typing import Any


def _count_latest(storage_meta: Any, *, record_type: str) -> int:
    try:
        rows = storage_meta.latest(record_type=record_type, limit=1)
        return int(len(rows))
    except Exception:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record-type", default="evidence.capture.frame")
    args = ap.parse_args()

    from autocapture_nx.kernel.loader import default_config_paths
    from autocapture_nx.ux.facade import KernelManager

    km = KernelManager(default_config_paths(), safe_mode=False, persistent=False, start_conductor=False)
    with km.session() as system:
        if system is None or not hasattr(system, "get"):
            print("0")
            return 2
        meta = system.get("storage.metadata")
        n = _count_latest(meta, record_type=str(args.record_type))
        print(str(n))
        return 0 if n > 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())

