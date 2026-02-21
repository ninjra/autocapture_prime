"""Canonical localhost service endpoints used by autocapture_prime."""

from __future__ import annotations

import os

VLM_ROOT_URL = str(os.environ.get("AUTOCAPTURE_VLM_ROOT_URL") or "").strip() or "http://127.0.0.1:8000"
VLM_BASE_URL = f"{VLM_ROOT_URL.rstrip('/')}/v1"
VLM_MODEL_ID = str(os.environ.get("AUTOCAPTURE_VLM_MODEL") or "").strip() or "internvl3_5_8b"

EMBEDDER_BASE_URL = str(os.environ.get("AUTOCAPTURE_EMBEDDER_BASE_URL") or "").strip() or "http://127.0.0.1:8001"
EMBEDDER_MODEL_ID = str(os.environ.get("AUTOCAPTURE_EMBEDDER_MODEL") or "").strip() or "BAAI/bge-small-en-v1.5"

GROUNDING_BASE_URL = str(os.environ.get("AUTOCAPTURE_GROUNDING_BASE_URL") or "").strip() or "http://127.0.0.1:8011"
HYPERVISOR_GATEWAY_BASE_URL = (
    str(os.environ.get("AUTOCAPTURE_HYPERVISOR_GATEWAY_BASE_URL") or "").strip() or "http://127.0.0.1:34221"
)
POPUP_QUERY_BASE_URL = str(os.environ.get("AUTOCAPTURE_POPUP_QUERY_BASE_URL") or "").strip() or "http://127.0.0.1:8787"
DEVTOOLS_BASE_URL = str(os.environ.get("AUTOCAPTURE_DEVTOOLS_BASE_URL") or "").strip() or "http://127.0.0.1:7411"

