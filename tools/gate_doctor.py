"""Gate: doctor checks must pass."""

from __future__ import annotations

from autocapture_nx.kernel.loader import Kernel, default_config_paths


def main() -> int:
    kernel = Kernel(default_config_paths(), safe_mode=True)
    kernel.boot()
    checks = kernel.doctor()
    failures = [check for check in checks if not check.ok]
    for check in failures:
        print(f"FAIL {check.name}: {check.detail}")
    if failures:
        return 1
    print("OK: doctor gate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
