import io
import json
import time
import unittest
from pathlib import Path
from typing import Any

from autocapture_nx.plugin_system.registry import CapabilityProxy, MultiCapabilityProxy
from autocapture_nx.processing.sst.pipeline import SSTPipeline

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - optional dependency guard
    Image = None
    ImageDraw = None


class _MetadataStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}

    def put_new(self, record_id: str, value: dict[str, Any]) -> None:
        if record_id in self.data:
            raise FileExistsError(record_id)
        self.data[record_id] = value

    def put(self, record_id: str, value: dict[str, Any]) -> None:
        self.data[record_id] = value

    def get(self, record_id: str, default: Any | None = None) -> Any:
        return self.data.get(record_id, default)

    def keys(self) -> list[str]:
        return list(self.data.keys())


class _EventBuilder:
    def journal_event(self, _event_type: str, payload: dict[str, Any], **_kwargs: Any) -> str:
        return payload.get("artifact_id", "event")

    def ledger_entry(self, _stage: str, **kwargs: Any) -> str:
        payload = kwargs.get("payload", {})
        return payload.get("artifact_id", "entry")


class _OCRProvider:
    def extract_tokens(self, _image_bytes: bytes) -> list[dict[str, Any]]:
        return []


class _StageHookProvider:
    def stages(self) -> list[str]:
        return ["ocr.onnx"]

    def run_stage(self, stage: str, _payload: dict[str, Any]) -> dict[str, Any]:
        if stage != "ocr.onnx":
            return {}
        return {
            "tokens": [
                {
                    "text": "",
                    "bbox": (-10, -10, -5, -5),
                    "confidence_bp": 120,
                }
            ]
        }


class _System:
    def __init__(self, config: dict[str, Any], caps: dict[str, Any]) -> None:
        self.config = config
        self._caps = caps

    def has(self, name: str) -> bool:
        return name in self._caps

    def get(self, name: str) -> Any:
        return self._caps[name]


def _make_image_bytes() -> bytes:
    if Image is None:
        return b""
    img = Image.new("RGB", (320, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), "RAW", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _load_default_config() -> dict[str, Any]:
    return json.loads(Path("config/default.json").read_text(encoding="utf-8"))


def _stage_hooks_capability(provider_id: str, provider: _StageHookProvider) -> MultiCapabilityProxy:
    policy = _load_default_config().get("plugins", {}).get("capabilities", {}).get("processing.stage.hooks", {})
    proxies = [(provider_id, CapabilityProxy(provider, network_allowed=False))]
    return MultiCapabilityProxy("processing.stage.hooks", proxies, policy)


@unittest.skipIf(Image is None, "Pillow is required for SST token tests")
class TestSSTTokensRaw(unittest.TestCase):
    def test_tokens_raw_keeps_invalid(self) -> None:
        config = _load_default_config()
        config["processing"]["sst"]["stage_providers"]["ocr.onnx"] = {
            "enabled": True,
            "provider_ids": [],
            "fanout": True,
            "max_providers": 0,
        }
        metadata = _MetadataStore()
        provider = _StageHookProvider()
        system = _System(
            config,
            {
                "storage.metadata": metadata,
                "ocr.engine": _OCRProvider(),
                "event.builder": _EventBuilder(),
                "processing.stage.hooks": _stage_hooks_capability("bad.token", provider),
            },
        )
        pipeline = SSTPipeline(system, extractor_id="test.sst.raw", extractor_version="0.1.0")
        result = pipeline.process_record(
            record_id="run1/segment/0",
            record={"record_type": "evidence.capture.segment", "ts_utc": "2024-01-01T00:00:00+00:00"},
            frame_bytes=_make_image_bytes(),
            allow_ocr=True,
            allow_vlm=False,
            should_abort=None,
            deadline_ts=time.time() + 30,
        )
        self.assertTrue(result.heavy_ran)
        state_key = next(k for k in metadata.keys() if k.startswith("run1/derived.sst.state/"))
        payload = metadata.get(state_key, {})
        state = payload.get("screen_state", {})
        raw_tokens = state.get("tokens_raw", ())
        self.assertTrue(raw_tokens, "tokens_raw should retain invalid entries")
        flagged = [t for t in raw_tokens if isinstance(t, dict) and t.get("flags", {}).get("invalid_text")]
        self.assertTrue(flagged, "invalid tokens should be flagged")
