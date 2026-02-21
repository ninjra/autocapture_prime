"""Gate: adversarial redesign recommendations must be implemented and validated.

This is intentionally strict when enabled: every ID in
docs/autocapture_prime_adversarial_redesign.md must be present and marked
implemented with deterministic validators.

By default this gate is meant to be run explicitly (or enabled in CI) once the
map is filled out; it is not yet wired into MOD-021 by default.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

from tools.traceability.generate_adversarial_redesign_traceability import main as gen_main  # noqa: E402
from tools.traceability.validate_adversarial_redesign_traceability import main as val_main  # noqa: E402


def main() -> int:
    # Hard require when running the gate.
    os.environ["AUTOCAPTURE_REQUIRE_ADVERSARIAL_REDESIGN_IMPLEMENTED"] = "1"
    code = gen_main()
    if code != 0:
        return code
    return val_main()


if __name__ == "__main__":
    raise SystemExit(main())

