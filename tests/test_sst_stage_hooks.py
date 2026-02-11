import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from autocapture.indexing.lexical import LexicalIndex
from autocapture_nx.kernel.canonical_json import dumps as canonical_dumps
from autocapture_nx.plugin_system.registry import CapabilityProxy, MultiCapabilityProxy
from autocapture_nx.processing.sst.pipeline import SSTPipeline

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover - optional dependency guard
    Image = None
    ImageDraw = None

if Image is None or ImageDraw is None:  # pragma: no cover - optional dependency guard
    raise unittest.SkipTest("Pillow not installed")


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
        canonical_dumps(payload)
        return payload.get("artifact_id", "event")

    def ledger_entry(self, _stage: str, **kwargs: Any) -> str:
        payload = kwargs.get("payload", {})
        canonical_dumps(payload)
        return payload.get("artifact_id", "entry")


class _OCRProvider:
    def extract_tokens(self, _image_bytes: bytes) -> list[dict[str, Any]]:
        return [
            {
                "text": "Base OCR",
                "bbox": (8, 8, 120, 32),
                "confidence": 0.92,
            }
        ]


class _StageHookProvider:
    def __init__(self, provider_id: str, *, token_text: str, extra_text: str, extra_meta: dict[str, Any]) -> None:
        self.provider_id = provider_id
        self._token_text = token_text
        self._extra_text = extra_text
        self._extra_meta = extra_meta

    def stages(self) -> list[str]:
        return ["ocr.onnx", "index.text"]

    def run_stage(self, stage: str, _payload: dict[str, Any]) -> dict[str, Any]:
        if stage == "ocr.onnx":
            return {
                "tokens": [
                    {
                        "text": self._token_text,
                        "bbox": (16, 40, 200, 72),
                        # Float confidence should be coerced to basis points.
                        "confidence_bp": 6500.0,
                    }
                ]
            }
        if stage == "index.text":
            return {
                "extra_docs": [
                    {
                        "text": self._extra_text,
                        "meta": dict(self._extra_meta),
                    }
                ]
            }
        return {}


class _System:
    def __init__(self, config: dict[str, Any], caps: dict[str, Any]) -> None:
        self.config = config
        self._caps = caps

    def has(self, name: str) -> bool:
        return name in self._caps

    def get(self, name: str) -> Any:
        return self._caps[name]


def _load_default_config() -> dict[str, Any]:
    return json.loads(Path("config/default.json").read_text(encoding="utf-8"))


def _make_image_bytes() -> bytes:
    assert Image is not None and ImageDraw is not None
    img = Image.new("RGB", (320, 180), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((12, 12), "Stage Hook Test", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _stage_hooks_capability(providers: dict[str, _StageHookProvider]) -> CapabilityProxy:
    preferred = ["hook.one", "hook.two"]
    policy = {
        "mode": "multi",
        "preferred": preferred,
        "provider_ids": [],
        "fanout": True,
        "max_providers": 0,
    }
    ordered = [pid for pid in preferred if pid in providers] + sorted(
        pid for pid in providers.keys() if pid not in preferred
    )
    proxies = [(pid, CapabilityProxy(providers[pid], network_allowed=False)) for pid in ordered]
    multi = MultiCapabilityProxy("processing.stage.hooks", proxies, policy)
    return CapabilityProxy(multi, network_allowed=False)


def _configure_stage_policies(config: dict[str, Any], overrides: dict[str, dict[str, Any]]) -> None:
    sst = config.setdefault("processing", {}).setdefault("sst", {})
    stage_providers = sst.setdefault("stage_providers", {})
    for stage, update in overrides.items():
        policy = stage_providers.setdefault(stage, {})
        policy.update(update)


def _run_pipeline(
    tmpdir: str,
    *,
    stage_overrides: dict[str, dict[str, Any]],
    redact_enabled: bool,
    extra_docs: dict[str, tuple[str, dict[str, Any]]] | None = None,
) -> tuple[_MetadataStore, dict[str, Any]]:
    config = _load_default_config()
    storage = config.setdefault("storage", {})
    storage["lexical_path"] = str(Path(tmpdir) / "lexical.db")
    storage["vector_path"] = str(Path(tmpdir) / "vector.db")
    storage["data_dir"] = str(tmpdir)
    storage["raw_first_local"] = True
    sst = config.setdefault("processing", {}).setdefault("sst", {})
    sst["heavy_always"] = True
    sst["redact_enabled"] = bool(redact_enabled)
    _configure_stage_policies(
        config,
        {
            "ocr.onnx": {"enabled": True, "provider_ids": [], "fanout": True, "max_providers": 0},
            "index.text": {"enabled": True, "provider_ids": [], "fanout": True, "max_providers": 0},
            **stage_overrides,
        },
    )

    metadata = _MetadataStore()
    events = _EventBuilder()
    providers: dict[str, _StageHookProvider] = {}
    for provider_id, token_text in (("hook.one", "HOOK_ONE"), ("hook.two", "HOOK_TWO")):
        doc_text, doc_meta = extra_docs.get(provider_id, ("STAGEHOOK_DEFAULT", {})) if extra_docs else (
            f"STAGEHOOK_{provider_id.replace('.', '_').upper()}",
            {},
        )
        providers[provider_id] = _StageHookProvider(
            provider_id,
            token_text=token_text,
            extra_text=doc_text,
            extra_meta=doc_meta,
        )

    system = _System(
        config,
        {
            "storage.metadata": metadata,
            "ocr.engine": _OCRProvider(),
            "event.builder": events,
            "processing.stage.hooks": _stage_hooks_capability(providers),
        },
    )

    pipeline = SSTPipeline(system, extractor_id="test.sst.hooks", extractor_version="0.1.0")
    record_id = "run1/segment/0"
    record = {
        "record_type": "evidence.capture.segment",
        "ts_utc": "2024-01-01T00:00:00+00:00",
        "container": {"type": "zip"},
    }
    result = pipeline.process_record(
        record_id=record_id,
        record=record,
        frame_bytes=_make_image_bytes(),
        allow_ocr=True,
        allow_vlm=False,
        should_abort=None,
        deadline_ts=time.time() + 30,
    )
    assert result.heavy_ran
    return metadata, storage


def _state_tokens(metadata: _MetadataStore) -> tuple[dict[str, Any], ...]:
    state_key = next(k for k in metadata.keys() if k.startswith("run1/derived.sst.state/"))
    state_payload = metadata.get(state_key, {})
    screen_state = state_payload.get("screen_state", {})
    tokens = screen_state.get("tokens", ())
    return tuple(tokens) if isinstance(tokens, (list, tuple)) else ()


def _extra_doc_payloads(metadata: _MetadataStore) -> list[dict[str, Any]]:
    extra_keys = [k for k in metadata.keys() if k.startswith("run1/derived.sst.text/extra/")]
    return [metadata.get(key, {}) for key in extra_keys]


@unittest.skipIf(Image is None, "Pillow is required for SST stage hook tests")
class SSTStageHookTests(unittest.TestCase):
    def test_stage_hooks_fanout_true_runs_all_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata, storage = _run_pipeline(
                tmpdir,
                stage_overrides={
                    "ocr.onnx": {"fanout": True, "provider_ids": []},
                    "index.text": {"fanout": True, "provider_ids": []},
                },
                redact_enabled=False,
            )
            provider_ids = {t.get("provider_id") for t in _state_tokens(metadata)}
            self.assertIn("hook.one", provider_ids)
            self.assertIn("hook.two", provider_ids)

            extra_payloads = _extra_doc_payloads(metadata)
            extra_providers = {payload.get("provider_id") for payload in extra_payloads}
            self.assertTrue({"hook.one", "hook.two"} <= extra_providers)

            lexical = LexicalIndex(storage["lexical_path"])
            hits = lexical.query("STAGEHOOK_HOOK_ONE", limit=10)
            self.assertTrue(any(hit["doc_id"].startswith("run1/derived.sst.text/extra/") for hit in hits))

    def test_stage_hooks_provider_filter_and_fanout_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata, _storage = _run_pipeline(
                tmpdir,
                stage_overrides={
                    "ocr.onnx": {"fanout": True, "provider_ids": ["hook.two"]},
                },
                redact_enabled=False,
            )
            provider_ids = {t.get("provider_id") for t in _state_tokens(metadata)}
            self.assertIn("hook.two", provider_ids)
            self.assertNotIn("hook.one", provider_ids)

        with tempfile.TemporaryDirectory() as tmpdir:
            metadata, _storage = _run_pipeline(
                tmpdir,
                stage_overrides={
                    "ocr.onnx": {"fanout": False, "provider_ids": []},
                },
                redact_enabled=False,
            )
            provider_ids = {t.get("provider_id") for t in _state_tokens(metadata)}
            self.assertIn("hook.one", provider_ids)
            self.assertNotIn("hook.two", provider_ids)

    def test_stage_hook_extra_docs_not_redacted_when_raw_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata, _storage = _run_pipeline(
                tmpdir,
                stage_overrides={
                    "index.text": {"fanout": True, "provider_ids": []},
                },
                redact_enabled=True,
                extra_docs={
                    "hook.one": (
                        "STAGEHOOK_EMAIL one@example.com",
                        {"contact": "two@example.com"},
                    )
                },
            )
            extra_payloads = _extra_doc_payloads(metadata)
            self.assertTrue(extra_payloads)
            # Raw-first local store disables redaction; verify sensitive text remains.
            joined = json.dumps(extra_payloads, sort_keys=True)
            self.assertIn("one@example.com", joined)
            self.assertIn("two@example.com", joined)
            self.assertNotIn("[REDACTED:email:", joined)


if __name__ == "__main__":
    unittest.main()
