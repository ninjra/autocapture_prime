from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from autocapture_nx.kernel.diagnostics_bundle import create_diagnostics_bundle


def test_diagnostics_bundle_contains_manifest_and_matches_schema(tmp_path: Path) -> None:
    cfg = {"storage": {"data_dir": str(tmp_path)}, "runtime": {"run_id": "run1"}}
    report = {"ok": True, "generated_at_utc": "t0", "checks": []}
    result = create_diagnostics_bundle(config=cfg, doctor_report=report, out_dir=tmp_path / "out", include_logs_tail_lines=0)

    path = Path(result.path)
    assert path.exists()
    with zipfile.ZipFile(path, "r") as zf:
        names = set(zf.namelist())
        assert "bundle_manifest.json" in names
        manifest = json.loads(zf.read("bundle_manifest.json").decode("utf-8"))

    # Validate against checked-in schema when jsonschema is available.
    schema_path = Path("contracts/diagnostics_bundle.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        import jsonschema  # type: ignore
    except Exception:
        pytest.skip("jsonschema not available")
    jsonschema.validate(manifest, schema)

