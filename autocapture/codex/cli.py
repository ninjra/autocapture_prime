"""Codex CLI entry points."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from autocapture.codex.report import build_report
from autocapture.codex.spec import DEFAULT_SPEC_PATH, load_spec
from autocapture.codex.validators import validate_requirement


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def cmd_validate(args: argparse.Namespace) -> int:
    spec = load_spec(Path(args.spec_path))
    results = [validate_requirement(req) for req in spec.requirements]
    report = build_report(spec.blueprint_id, spec.version, results)
    payload = report.to_dict()
    _write_json(Path("artifacts/codex_report.json"), payload)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        summary = report.summary()
        print(f"codex: {summary['passed']}/{summary['total']} passed")
    return 0 if report.summary()["failed"] == 0 else 1


def cmd_list(args: argparse.Namespace) -> int:
    spec = load_spec(Path(args.spec_path))
    results = [validate_requirement(req) for req in spec.requirements]
    for req, res in zip(spec.requirements, results, strict=True):
        status = "PASS" if res.ok else "FAIL"
        print(f"{req.req_id} {status} {req.title}")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    spec = load_spec(Path(args.spec_path))
    match = next((req for req in spec.requirements if req.req_id == args.req_id), None)
    if match is None:
        print(f"unknown requirement: {args.req_id}")
        return 2
    payload = {
        "id": match.req_id,
        "title": match.title,
        "pillars": match.pillars,
        "artifacts": match.artifacts,
        "validators": [
            {"type": v.type, **v.config}
            for v in match.validators
        ],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def cmd_pillar_gates(_args: argparse.Namespace) -> int:
    from autocapture.tools.pillar_gate import run_all_gates

    ok = run_all_gates()
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autocapture codex")
    parser.add_argument("--spec-path", default=str(DEFAULT_SPEC_PATH))
    sub = parser.add_subparsers(dest="codex_cmd", required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--json", action="store_true", default=False)
    validate.set_defaults(func=cmd_validate)

    listing = sub.add_parser("list")
    listing.set_defaults(func=cmd_list)

    explain = sub.add_parser("explain")
    explain.add_argument("req_id")
    explain.add_argument("--json", action="store_true", default=False)
    explain.set_defaults(func=cmd_explain)

    pillar = sub.add_parser("pillar-gates")
    pillar.set_defaults(func=cmd_pillar_gates)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))
