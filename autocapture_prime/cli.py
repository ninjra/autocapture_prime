"""Legacy compatibility shim for autocapture-prime."""

from __future__ import annotations

import os
import sys

from autocapture_nx.cli import build_parser as build_nx_parser
from autocapture_nx.kernel.errors import AutocaptureError

_WARNED = False


def _warn_deprecated() -> None:
    global _WARNED  # noqa: PLW0603
    if _WARNED:
        return
    if str(os.getenv("AUTOCAPTURE_PRIME_SILENCE_DEPRECATION", "")).strip().lower() in {"1", "true", "yes", "on"}:
        _WARNED = True
        return
    print(
        "autocapture-prime is deprecated; use autocapture (NX canonical CLI).",
        file=sys.stderr,
    )
    _WARNED = True


def build_parser():
    parser = build_nx_parser()
    parser.prog = "autocapture-prime"
    return parser


def main(argv: list[str] | None = None) -> int:
    _warn_deprecated()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except AutocaptureError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
