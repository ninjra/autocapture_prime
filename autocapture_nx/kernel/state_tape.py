"""State tape helpers for NX runtime.

The NX architecture uses a "state tape" concept to persist derived and runtime
state in a queryable way. Today, the most portable, low-friction persistence
layer is the metadata store (SQLite/SQLCipher via storage plugins).

This module provides deterministic helpers for recording pipeline-level runtime
artifacts (e.g., pipeline DAG) without introducing heavy dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from autocapture_nx.kernel.hashing import sha256_canonical


PIPELINE_DAG_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PipelineDAG:
    schema_version: int
    stages: tuple[str, ...]
    deps: tuple[tuple[str, str], ...]  # (from_stage, to_stage)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["stages"] = list(self.stages)
        payload["deps"] = [list(pair) for pair in self.deps]
        return payload


def build_pipeline_dag(*, enabled_caps: set[str]) -> PipelineDAG:
    """Build a minimal capture->process->index->query DAG.

    The DAG is intentionally conservative and stable:
    - It does not depend on wall-clock time.
    - It uses only capability presence to include optional stages.
    """

    stages: list[str] = ["capture", "ingest", "process", "index", "query"]
    deps: list[tuple[str, str]] = [("capture", "ingest"), ("ingest", "process"), ("process", "index"), ("index", "query")]

    # Optional: state layer / timeline can be added if state tape is enabled.
    if "storage.state_tape" in enabled_caps or "state.layer" in enabled_caps:
        if "state" not in stages:
            stages.insert(stages.index("index"), "state")
            deps = [
                ("capture", "ingest"),
                ("ingest", "process"),
                ("process", "state"),
                ("state", "index"),
                ("index", "query"),
            ]

    return PipelineDAG(
        schema_version=PIPELINE_DAG_SCHEMA_VERSION,
        stages=tuple(stages),
        deps=tuple(sorted(set(deps))),
    )


def persist_pipeline_dag(
    metadata_store: Any,
    *,
    run_id: str,
    ts_utc: str,
    dag: PipelineDAG,
) -> str:
    """Persist the pipeline DAG as a deterministic metadata record.

    Returns the record_id written.
    """

    record_id = f"{run_id}/derived.pipeline_dag/v{int(dag.schema_version)}"
    payload: dict[str, Any] = {
        "record_type": "derived.pipeline_dag",
        "schema_version": int(dag.schema_version),
        "run_id": str(run_id),
        "ts_utc": str(ts_utc),
        "dag": dag.to_dict(),
    }
    payload["payload_hash"] = sha256_canonical({k: v for k, v in payload.items() if k != "payload_hash"})
    if hasattr(metadata_store, "put_replace"):
        metadata_store.put_replace(record_id, payload)
    else:
        metadata_store.put(record_id, payload)
    return record_id

