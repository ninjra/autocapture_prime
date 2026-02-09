from __future__ import annotations

from autocapture_nx.kernel.state_tape import build_pipeline_dag


def test_pipeline_dag_deterministic_from_capabilities_set() -> None:
    caps = {"capture.source", "storage.metadata", "retrieval.strategy"}
    dag1 = build_pipeline_dag(enabled_caps=set(caps))
    dag2 = build_pipeline_dag(enabled_caps=set(caps))
    assert dag1 == dag2
    assert dag1.schema_version >= 1
    assert list(dag1.stages) == ["capture", "ingest", "process", "index", "query"]
    assert ("capture", "ingest") in set(dag1.deps)


def test_pipeline_dag_includes_state_stage_when_state_tape_enabled() -> None:
    caps = {"storage.state_tape", "storage.metadata"}
    dag = build_pipeline_dag(enabled_caps=set(caps))
    assert "state" in set(dag.stages)
    assert ("process", "state") in set(dag.deps)
    assert ("state", "index") in set(dag.deps)

