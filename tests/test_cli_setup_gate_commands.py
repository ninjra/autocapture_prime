from __future__ import annotations

from autocapture_nx.cli import build_parser


def test_setup_command_is_registered() -> None:
    parser = build_parser()
    args = parser.parse_args(["setup", "--profile", "personal_4090"])
    assert getattr(args, "command") == "setup"
    assert callable(getattr(args, "func", None))


def test_gate_command_is_registered() -> None:
    parser = build_parser()
    args = parser.parse_args(["gate", "--profile", "golden_qh", "--skip-q40"])
    assert getattr(args, "command") == "gate"
    assert callable(getattr(args, "func", None))
