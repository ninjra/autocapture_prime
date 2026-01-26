"""Rules CLI for MX."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from autocapture.rules.ledger import RulesLedger
from autocapture.rules.store import RulesStore


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="autocapture rules")
    parser.add_argument("--ledger", default="data/rules.ndjson")
    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add")
    add.add_argument("rule_id")
    add.add_argument("--payload", default="{}")

    list_cmd = sub.add_parser("list")

    args = parser.parse_args(argv)
    ledger = RulesLedger(Path(args.ledger))

    if args.cmd == "add":
        payload = json.loads(args.payload)
        entry = {
            "rule_id": args.rule_id,
            "action": "add",
            "payload": payload,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
        }
        ledger.append(entry)
        return 0

    if args.cmd == "list":
        store = RulesStore(ledger)
        state = store.rebuild_state()
        print(json.dumps(state, indent=2, sort_keys=True))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
