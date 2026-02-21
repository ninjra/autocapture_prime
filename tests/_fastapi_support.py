"""FastAPI/Starlette TestClient support checks.

Some environments have FastAPI installed but a broken/hanging TestClient stack
(often due to dependency/version mismatches). Gate those tests behind a short,
subprocess-based smoke check so the suite fails fast and deterministically.
"""

from __future__ import annotations

import os
import subprocess
import sys


def fastapi_testclient_usable(*, timeout_s: float = 10.0) -> bool:
    code = (
        "from fastapi import FastAPI\n"
        "from fastapi.testclient import TestClient\n"
        "app = FastAPI()\n"
        "app.add_api_route('/', lambda: {'ok': True}, methods=['GET'])\n"
        "client = TestClient(app)\n"
        "resp = client.get('/')\n"
        "assert resp.status_code == 200\n"
        "print('OK')\n"
    )
    env: dict[str, str] = dict(os.environ)
    # Ensure repo imports work if the smoke check needs them in the future.
    env["PYTHONPATH"] = os.getcwd() + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=float(timeout_s),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False
    return proc.returncode == 0 and "OK" in (proc.stdout or "")
