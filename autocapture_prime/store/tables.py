from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_rows(rows: list[dict[str, Any]], target_root: Path, table_name: str) -> Path:
    """Write table rows as parquet when available, else deterministic NDJSON."""
    target_root.mkdir(parents=True, exist_ok=True)
    parquet_path = target_root / f"{table_name}.parquet"
    try:
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore

        table = pa.Table.from_pylist(rows)
        pq.write_table(table, parquet_path, compression="zstd")
        return parquet_path
    except Exception:
        ndjson_path = target_root / f"{table_name}.ndjson"
        with ndjson_path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        return ndjson_path
