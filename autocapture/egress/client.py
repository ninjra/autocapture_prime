"""Compatibility wrapper for egress client.

The adversarial redesign doc references `autocapture/egress/client.py`.
The actual implementation lives in `autocapture/core/http.py`.
"""

from __future__ import annotations

from autocapture.core.http import EgressClient  # noqa: F401

