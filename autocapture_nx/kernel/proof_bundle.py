"""Proof bundle export for citations and provenance."""

from __future__ import annotations

import base64
import hashlib
import json
import hmac
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from autocapture_nx.kernel.canonical_json import dumps
from autocapture_nx.kernel.crypto import derive_key
from autocapture_nx.kernel.hashing import sha256_text
from autocapture_nx.kernel.ids import encode_record_id_component
from autocapture_nx.kernel.policy_snapshot import policy_snapshot_hash as _policy_hash
from autocapture_nx.plugin_system.api import PluginContext
from plugins.builtin.citation_basic.plugin import CitationValidator


@dataclass(frozen=True)
class ProofBundleReport:
    ok: bool
    output_path: str
    evidence_ids: list[str]
    derived_ids: list[str]
    edge_ids: list[str]
    ledger_entries: int
    anchors: int
    blobs: int
    errors: list[str]
    warnings: list[str]


def export_proof_bundle(
    *,
    metadata: Any,
    media: Any,
    keyring: Any | None = None,
    ledger_path: str | Path,
    anchor_path: str | Path,
    output_path: str | Path,
    evidence_ids: Iterable[str],
    citations: list[dict[str, Any]] | None = None,
) -> ProofBundleReport:
    evidence_list = sorted({str(eid) for eid in evidence_ids if eid})
    errors: list[str] = []
    warnings: list[str] = []
    if not evidence_list and not citations:
        return ProofBundleReport(
            ok=False,
            output_path=str(output_path),
            evidence_ids=[],
            derived_ids=[],
            edge_ids=[],
            ledger_entries=0,
            anchors=0,
            blobs=0,
            errors=["missing_evidence_ids"],
            warnings=[],
        )
    if citations:
        for citation in citations:
            evidence_id = citation.get("evidence_id") or citation.get("span_id")
            if evidence_id:
                evidence_list.append(str(evidence_id))
        evidence_list = sorted(set(evidence_list))

    ledger_path = Path(ledger_path)
    anchor_path = Path(anchor_path)
    output_path = Path(output_path)

    records, derived_ids, edge_ids, missing = _collect_records(metadata, evidence_list)
    if missing:
        warnings.append(f"missing_evidence:{len(missing)}")

    all_record_ids = set(evidence_list) | set(derived_ids) | set(edge_ids)
    ledger_entries, ledger_hashes, ledger_errors = _collect_ledger_entries(
        ledger_path, all_record_ids, citations
    )
    for err in ledger_errors:
        if err.startswith("ledger_missing") or err == "ledger_read_failed":
            errors.append(err)
        else:
            warnings.append(err)

    anchors, anchor_errors = _collect_anchor_entries(anchor_path, ledger_hashes, citations)
    for err in anchor_errors:
        if err.startswith("anchor_missing") and citations:
            errors.append(err)
        else:
            warnings.append(err)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir)
        blobs_dir = tmp_root / "blobs"
        blobs_dir.mkdir(parents=True, exist_ok=True)
        blob_manifest: dict[str, dict[str, Any]] = {}
        blob_count = 0
        for record_id in evidence_list:
            try:
                data = media.get(record_id)
            except Exception:
                data = None
            if not data:
                warnings.append(f"blob_missing:{record_id}")
                continue
            blob_name = f"{encode_record_id_component(record_id)}.bin"
            blob_path = blobs_dir / blob_name
            blob_path.write_bytes(data)
            blob_hash = hashlib.sha256(data).hexdigest()
            blob_manifest[record_id] = {"file": f"blobs/{blob_name}", "sha256": blob_hash}
            blob_count += 1

        metadata_path = tmp_root / "metadata.jsonl"
        _write_metadata(metadata_path, records)

        ledger_out = tmp_root / "ledger.ndjson"
        _write_jsonl(ledger_out, ledger_entries)

        anchor_out = tmp_root / "anchors.ndjson"
        _write_jsonl(anchor_out, anchors)

        # META-06: include full policy snapshots referenced by the ledger entries.
        policy_hashes = sorted(
            {
                str(entry.get("policy_snapshot_hash"))
                for entry in ledger_entries
                if isinstance(entry, dict) and entry.get("policy_snapshot_hash")
            }
        )
        policy_dir = tmp_root / "policy_snapshots"
        if policy_hashes:
            policy_dir.mkdir(parents=True, exist_ok=True)
        for policy_hash in policy_hashes:
            record_id = f"policy_snapshot/{policy_hash}"
            record = None
            try:
                record = metadata.get(record_id)
            except Exception:
                record = None
            if not isinstance(record, dict):
                warnings.append(f"policy_snapshot_missing:{policy_hash}")
                continue
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else None
            if payload is None:
                warnings.append(f"policy_snapshot_invalid:{policy_hash}")
                continue
            (policy_dir / f"{policy_hash}.json").write_text(
                json.dumps(payload, sort_keys=True, indent=2),
                encoding="utf-8",
            )

        if blob_manifest:
            (blobs_dir / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "files": blob_manifest}, sort_keys=True, indent=2),
                encoding="utf-8",
            )

        if citations is not None:
            (tmp_root / "citations.json").write_text(
                json.dumps(citations, sort_keys=True, indent=2),
                encoding="utf-8",
            )

        verification = _build_verification_report(
            metadata=metadata,
            keyring=keyring,
            ledger_path=ledger_path,
            anchor_path=anchor_path,
            citations=citations,
        )
        (tmp_root / "verification.json").write_text(
            json.dumps(verification, sort_keys=True, indent=2),
            encoding="utf-8",
        )

        bundle_files = _bundle_files_manifest(tmp_root)
        manifest = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "evidence_ids": evidence_list,
            "derived_ids": sorted(derived_ids),
            "edge_ids": sorted(edge_ids),
            "record_count": len(records),
            "ledger_entries": len(ledger_entries),
            "anchors": len(anchors),
            "blobs": blob_count,
            "policy_snapshot_hashes": policy_hashes,
            "bundle_files": bundle_files,
            "files": {
                "metadata": "metadata.jsonl",
                "ledger": "ledger.ndjson",
                "anchors": "anchors.ndjson",
                "verification": "verification.json",
                "blobs_manifest": "blobs/manifest.json" if blob_manifest else None,
                "citations": "citations.json" if citations is not None else None,
                "policy_snapshots_dir": "policy_snapshots" if policy_hashes else None,
            },
        }
        (tmp_root / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        sig = _sign_manifest(tmp_root / "manifest.json", keyring)
        if sig is not None:
            (tmp_root / "manifest.sig.json").write_text(
                json.dumps(sig, sort_keys=True, indent=2),
                encoding="utf-8",
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(tmp_root.rglob("*")):
                if path.is_dir():
                    continue
                rel = path.relative_to(tmp_root).as_posix()
                zf.write(path, rel)

    ok = not errors
    return ProofBundleReport(
        ok=ok,
        output_path=str(output_path),
        evidence_ids=evidence_list,
        derived_ids=sorted(derived_ids),
        edge_ids=sorted(edge_ids),
        ledger_entries=len(ledger_entries),
        anchors=len(anchors),
        blobs=blob_count,
        errors=errors,
        warnings=warnings,
    )


def _collect_records(
    metadata: Any, evidence_ids: list[str]
) -> tuple[dict[str, dict[str, Any]], set[str], set[str], list[str]]:
    records: dict[str, dict[str, Any]] = {}
    derived_ids: set[str] = set()
    edge_ids: set[str] = set()
    missing: list[str] = []
    keys = list(getattr(metadata, "keys", lambda: [])())
    evidence_set = set(evidence_ids)
    for record_id in evidence_ids:
        record = metadata.get(record_id)
        if not isinstance(record, dict):
            missing.append(record_id)
            continue
        records[record_id] = record
    for record_id in keys:
        record = metadata.get(record_id, {})
        if not isinstance(record, dict):
            continue
        record_type = str(record.get("record_type", ""))
        if record_type.startswith("derived."):
            source_id = record.get("source_id") or record.get("parent_evidence_id")
            if source_id in evidence_set:
                records[record_id] = record
                derived_ids.add(record_id)
        if record_type == "derived.graph.edge":
            parent_id = record.get("parent_id")
            child_id = record.get("child_id")
            if parent_id in evidence_set or child_id in evidence_set:
                records[record_id] = record
                edge_ids.add(record_id)
    if derived_ids:
        for record_id in keys:
            record = metadata.get(record_id, {})
            if not isinstance(record, dict):
                continue
            record_type = str(record.get("record_type", ""))
            if record_type != "derived.graph.edge":
                continue
            parent_id = record.get("parent_id")
            child_id = record.get("child_id")
            if parent_id in derived_ids or child_id in derived_ids:
                records[record_id] = record
                edge_ids.add(record_id)
    return records, derived_ids, edge_ids, missing


def _collect_ledger_entries(
    ledger_path: Path,
    record_ids: set[str],
    citations: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], set[str], list[str]]:
    entries: list[dict[str, Any]] = []
    entry_hashes: set[str] = set()
    errors: list[str] = []
    if not ledger_path.exists():
        return entries, entry_hashes, [f"ledger_missing:{ledger_path}"]
    heads = set()
    if citations:
        for citation in citations:
            head = citation.get("ledger_head")
            if head:
                heads.add(str(head))
    try:
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except Exception:
                errors.append("ledger_line_invalid")
                continue
            entry_hash = entry.get("entry_hash")
            inputs = entry.get("inputs") or []
            outputs = entry.get("outputs") or []
            if entry_hash and entry_hash in heads:
                entries.append(entry)
                entry_hashes.add(entry_hash)
                continue
            if _intersects(record_ids, inputs) or _intersects(record_ids, outputs):
                entries.append(entry)
                if entry_hash:
                    entry_hashes.add(entry_hash)
    except Exception:
        errors.append("ledger_read_failed")
    return entries, entry_hashes, errors


def _collect_anchor_entries(
    anchor_path: Path,
    ledger_hashes: set[str],
    citations: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    anchors: list[dict[str, Any]] = []
    errors: list[str] = []
    if not anchor_path.exists():
        return anchors, [f"anchor_missing:{anchor_path}"]
    anchor_refs: set[tuple[Any, Any]] = set()
    if citations:
        for citation in citations:
            anchor_ref = citation.get("anchor_ref")
            if isinstance(anchor_ref, dict):
                anchor_refs.add((anchor_ref.get("anchor_seq"), anchor_ref.get("ledger_head_hash")))
    try:
        for line in anchor_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = _decode_anchor_line(line)
            if not isinstance(record, dict):
                continue
            anchor_seq = record.get("anchor_seq")
            ledger_head = record.get("ledger_head_hash")
            if (anchor_seq, ledger_head) in anchor_refs or ledger_head in ledger_hashes:
                anchors.append(_sanitize_anchor_record(record))
    except Exception:
        errors.append("anchor_read_failed")
    return anchors, errors


def _build_verification_report(
    *,
    metadata: Any,
    keyring: Any | None,
    ledger_path: Path,
    anchor_path: Path,
    citations: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    report: dict[str, Any] = {"ledger_ok": None, "anchor_ok": None, "citations_ok": None, "errors": []}
    ledger_ok, ledger_errors = _verify_ledger_file(ledger_path)
    report["ledger_ok"] = ledger_ok
    report["ledger_errors"] = ledger_errors
    anchor_ok, anchor_errors = _verify_anchor_file(anchor_path)
    report["anchor_ok"] = anchor_ok
    report["anchor_errors"] = anchor_errors
    if citations is not None:
        def get_capability(name: str):
            if name == "storage.metadata":
                return metadata
            if name == "storage.keyring":
                return keyring
            return None

        validator = CitationValidator(
            "citation.validator",
            PluginContext(
                config={"storage": {"data_dir": str(ledger_path.parent), "anchor": {"path": str(anchor_path)}}},
                get_capability=get_capability,
                logger=lambda _m: None,
            ),
        )
        result = validator.resolve(citations)
        report["citations_ok"] = bool(result.get("ok"))
        report["citations_errors"] = result.get("errors", [])

    # META-06: verify policy snapshots exist and match the hashes referenced in the ledger.
    missing: list[str] = []
    mismatched: list[str] = []
    try:
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            ph = entry.get("policy_snapshot_hash")
            if not ph:
                continue
            record_id = f"policy_snapshot/{ph}"
            rec = metadata.get(record_id) if hasattr(metadata, "get") else None
            if not isinstance(rec, dict) or not isinstance(rec.get("payload"), dict):
                missing.append(str(ph))
                continue
            payload = rec["payload"]
            expected = _policy_hash(payload)
            if expected != str(ph):
                mismatched.append(str(ph))
    except Exception:
        # Best-effort: keep verification report stable even if policy snapshot checks fail.
        missing = missing
        mismatched = mismatched
    report["policy_snapshot"] = {
        "ok": (not missing and not mismatched),
        "missing": sorted(set(missing)),
        "mismatched": sorted(set(mismatched)),
    }
    return report


def _verify_ledger_file(path: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not path.exists():
        return False, ["ledger_missing"]
    prev = ""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            entry_hash = entry.get("entry_hash")
            payload = dict(entry)
            payload.pop("entry_hash", None)
            canonical = dumps(payload)
            expected = sha256_text(canonical + (payload.get("prev_hash") or ""))
            if entry_hash != expected:
                errors.append("ledger_hash_mismatch")
            if payload.get("prev_hash") != prev and prev:
                errors.append("ledger_chain_gap")
            prev = entry_hash or prev
    except Exception:
        errors.append("ledger_read_failed")
    return len(errors) == 0, errors


def _verify_anchor_file(path: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not path.exists():
        return False, ["anchor_missing"]
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = _decode_anchor_line(line)
            if not isinstance(record, dict):
                errors.append("anchor_decode_failed")
                continue
            if "anchor_seq" not in record or "ledger_head_hash" not in record:
                errors.append("anchor_missing_fields")
    except Exception:
        errors.append("anchor_read_failed")
    return len(errors) == 0, errors


def _write_metadata(path: Path, records: dict[str, dict[str, Any]]) -> None:
    lines = []
    for record_id in sorted(records.keys()):
        lines.append(json.dumps({"record_id": record_id, "record": records[record_id]}, sort_keys=True))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    lines = [json.dumps(row, sort_keys=True) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _intersects(needles: set[str], values: Any) -> bool:
    if not needles:
        return False
    if not values:
        return False
    for item in values:
        if item in needles:
            return True
    return False


def _sanitize_anchor_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = dict(record)
    payload.pop("anchor_hmac", None)
    payload.pop("anchor_key_id", None)
    return payload


def _decode_anchor_line(line: str) -> dict[str, Any] | None:
    if line.startswith("DPAPI:"):
        data = line.split("DPAPI:", 1)[1]
        try:
            raw = base64.b64decode(data)
            from autocapture_nx.windows.dpapi import unprotect

            decoded = unprotect(raw)
            return json.loads(decoded.decode("utf-8"))
        except Exception:
            return None
    try:
        return json.loads(line)
    except Exception:
        return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bundle_files_manifest(root: Path) -> list[dict[str, Any]]:
    """Deterministic file list for tamper detection (SEC-07/QA-08)."""

    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            files.append({"path": rel, "sha256": _sha256_file(path), "bytes": int(path.stat().st_size)})
        except Exception:
            continue
    files.sort(key=lambda row: (str(row.get("path") or ""), str(row.get("sha256") or "")))
    return files


def _sign_manifest(manifest_path: Path, keyring: Any | None) -> dict[str, Any] | None:
    """Sign manifest.json with an HMAC derived from the anchor key."""

    if keyring is None:
        return None
    try:
        key_id, root = keyring.active_key("anchor")
        key = derive_key(root, "proof_bundle_manifest")
    except Exception:
        return None
    try:
        manifest_bytes = manifest_path.read_bytes()
    except Exception:
        return None
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    signature_hex = hmac.new(key, manifest_sha.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "schema_version": 1,
        "algo": "hmac-sha256",
        "key_id": str(key_id),
        "manifest_sha256": str(manifest_sha),
        "signature_hex": str(signature_hex),
    }


def verify_proof_bundle(bundle_path: str | Path, *, keyring: Any | None) -> dict[str, Any]:
    """Verify proof bundle integrity (SEC-07/QA-08)."""

    path = Path(bundle_path)
    if not path.exists():
        return {"ok": False, "error": "bundle_missing"}
    try:
        with zipfile.ZipFile(path, "r") as zf:
            manifest_bytes = zf.read("manifest.json")
            sig_raw = zf.read("manifest.sig.json")
    except KeyError:
        return {"ok": False, "error": "signature_missing"}
    except Exception as exc:
        return {"ok": False, "error": f"bundle_read_failed:{type(exc).__name__}"}
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except Exception:
        return {"ok": False, "error": "manifest_invalid_json"}
    if not isinstance(manifest, dict):
        return {"ok": False, "error": "manifest_invalid_shape"}
    try:
        sig = json.loads(sig_raw.decode("utf-8"))
    except Exception:
        return {"ok": False, "error": "signature_invalid_json"}
    if not isinstance(sig, dict):
        return {"ok": False, "error": "signature_invalid_shape"}
    if sig.get("algo") != "hmac-sha256":
        return {"ok": False, "error": "signature_algo_unsupported"}
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if str(sig.get("manifest_sha256") or "") != manifest_sha:
        return {"ok": False, "error": "manifest_sha256_mismatch"}
    if keyring is None:
        return {"ok": False, "error": "keyring_missing"}
    key_id = str(sig.get("key_id") or "").strip()
    signature_hex = str(sig.get("signature_hex") or "").strip()
    if not key_id or not signature_hex:
        return {"ok": False, "error": "signature_missing_fields"}
    try:
        root = keyring.key_for("anchor", key_id)
        key = derive_key(root, "proof_bundle_manifest")
    except Exception:
        return {"ok": False, "error": "signature_key_unavailable"}
    expected = hmac.new(key, manifest_sha.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_hex):
        return {"ok": False, "error": "signature_mismatch"}

    expected_files = manifest.get("bundle_files", [])
    if not isinstance(expected_files, list):
        return {"ok": False, "error": "bundle_files_missing"}
    expected_map: dict[str, dict[str, Any]] = {}
    for row in expected_files:
        if not isinstance(row, dict):
            continue
        rel = str(row.get("path") or "")
        if rel:
            expected_map[rel] = row
    try:
        with zipfile.ZipFile(path, "r") as zf:
            for rel, row in sorted(expected_map.items()):
                try:
                    data = zf.read(rel)
                except KeyError:
                    return {"ok": False, "error": f"bundle_file_missing:{rel}"}
                sha = hashlib.sha256(data).hexdigest()
                if sha != str(row.get("sha256") or ""):
                    return {"ok": False, "error": f"bundle_file_sha256_mismatch:{rel}"}
                if int(len(data)) != int(row.get("bytes") or 0):
                    return {"ok": False, "error": f"bundle_file_size_mismatch:{rel}"}
    except Exception as exc:
        return {"ok": False, "error": f"bundle_verify_failed:{type(exc).__name__}"}
    return {"ok": True, "manifest_sha256": manifest_sha, "key_id": key_id}
