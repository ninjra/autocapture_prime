"""Generate adversarial redesign traceability manifest.

Output: tools/traceability/adversarial_redesign_traceability.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from tools.traceability.adversarial_redesign_inventory import (  # noqa: E402
    compute_status,
    parse_redesign_doc,
    split_enforcement_locations,
    split_regression_validators,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    doc_path = _REPO_ROOT / "docs" / "autocapture_prime_adversarial_redesign.md"
    map_path = _REPO_ROOT / "tools" / "traceability" / "adversarial_redesign_map.json"
    out_path = _REPO_ROOT / "tools" / "traceability" / "adversarial_redesign_traceability.json"

    items = parse_redesign_doc(doc_path)
    mapping = _load_json(map_path)
    mapped_items = mapping.get("items", [])
    mapped_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(mapped_items, list):
        for entry in mapped_items:
            if not isinstance(entry, dict):
                continue
            rid = str(entry.get("id", "")).strip()
            if rid:
                mapped_by_id[rid] = entry

    out_items: list[dict[str, Any]] = []
    for it in items:
        mapped = dict(mapped_by_id.get(it.item_id, {}))

        # Defaults from the redesign doc.
        evidence_default = split_enforcement_locations(it.field("enforcement_location"))
        validators_default, needs_work = split_regression_validators(it.field("regression_detection"))
        status_default = compute_status(
            repo_root=_REPO_ROOT,
            evidence=evidence_default,
            validators=validators_default,
            needs_work=needs_work,
        )

        status = str(mapped.get("status", status_default) or status_default)
        if status not in {"missing", "partial", "implemented"}:
            status = status_default
        evidence = mapped.get("evidence", evidence_default)
        validators = mapped.get("validators", validators_default)
        out_items.append(
            {
                "id": it.item_id,
                "title": it.title,
                "status": status,
                "evidence": [str(x) for x in evidence] if isinstance(evidence, list) else [],
                "validators": [str(x) for x in validators] if isinstance(validators, list) else [],
                "notes": str(mapped.get("notes", "")).strip() if mapped.get("notes") else "",
            }
        )

    payload = {
        "generated_utc": _utc_now(),
        "source_doc": str(doc_path.relative_to(_REPO_ROOT)),
        "items": sorted(out_items, key=lambda row: row["id"]),
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"OK: wrote {out_path.relative_to(_REPO_ROOT)} items={len(out_items)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
