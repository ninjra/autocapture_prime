from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import uvicorn

from autocapture_prime.config import load_prime_config
from autocapture_prime.ingest.pipeline import ingest_one_session
from autocapture_prime.ingest.session_scanner import SessionScanner
from autocapture_prime.store.index import build_lexical_index
from services.chronicle_api.app import create_app


def _state_db(storage_root: Path) -> Path:
    return storage_root / "ingest_state.db"


def cmd_ingest(args: argparse.Namespace) -> int:
    cfg = load_prime_config(args.config)
    scanner = SessionScanner(cfg.spool_root, _state_db(cfg.storage_root))
    if args.watch:
        while True:
            _run_once(scanner, cfg)
            time.sleep(cfg.poll_interval_ms / 1000.0)
    return _run_once(scanner, cfg)


def _run_once(scanner: SessionScanner, cfg) -> int:
    summaries = []
    for session in scanner.list_pending():
        summary = ingest_one_session(session, cfg)
        scanner.mark_processed(session)
        summaries.append(summary)
    print(json.dumps({"ok": True, "processed": len(summaries), "summaries": summaries}, indent=2, sort_keys=True))
    return 0


def cmd_build_index(args: argparse.Namespace) -> int:
    cfg = load_prime_config(args.config)
    session_ids: list[str] = []
    if args.all:
        session_ids = [p.name for p in cfg.storage_root.iterdir() if p.is_dir()] if cfg.storage_root.exists() else []
    elif args.session:
        session_ids = [args.session]
    results = []
    for session_id in sorted(session_ids):
        root = cfg.storage_root / session_id
        rows = []
        for name in ("ocr_spans.ndjson", "elements.ndjson"):
            path = root / name
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rows.append(json.loads(line))
        idx = build_lexical_index(rows, root / "lexical_index.json")
        results.append({"session_id": session_id, "rows": len(rows), "index": str(idx)})
    print(json.dumps({"ok": True, "results": results}, indent=2, sort_keys=True))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    cfg = load_prime_config(args.config)
    app = create_app(args.config)
    uvicorn.run(app, host=cfg.api_host, port=cfg.api_port, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autocapture_prime")
    parser.add_argument("--config", default="config/autocapture_prime.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest")
    ingest.add_argument("--once", action="store_true")
    ingest.add_argument("--watch", action="store_true")
    ingest.set_defaults(func=cmd_ingest)

    index = sub.add_parser("build-index")
    index.add_argument("--session", default="")
    index.add_argument("--all", action="store_true")
    index.set_defaults(func=cmd_build_index)

    serve = sub.add_parser("serve")
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "ingest" and not args.watch:
        args.once = True
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
