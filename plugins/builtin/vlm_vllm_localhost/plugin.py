"""Localhost-only VLM via an OpenAI-compatible server (for example vLLM)."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from autocapture_nx.inference.openai_compat import OpenAICompatClient, image_bytes_to_data_url
from autocapture_nx.inference.vllm_endpoint import EXTERNAL_VLLM_BASE_URL, enforce_external_vllm_base_url
from autocapture_nx.plugin_system.api import PluginBase, PluginContext

try:  # pragma: no cover - optional dependency guard
    from PIL import Image

    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency guard
    Image = None  # type: ignore[assignment]
    _PIL_AVAILABLE = False


DEFAULT_LAYOUT_PROMPT = (
    "Return STRICT JSON only with schema "
    '{"elements":[{"type":"window","bbox":[x1,y1,x2,y2],"text":"visible text",'
    '"interactable":true,"state":{"enabled":true,"selected":false,"focused":false,"expanded":false},'
    '"children":[...]}]}. '
    "Use absolute pixel coordinates relative to the provided image. "
    "Detect visible UI structure and preserve nesting. "
    "Do not emit placeholder literals like 'string' or enum lists; fill values from the actual image. "
    "Do not include markdown, prose, or keys outside this schema."
)

DEFAULT_THUMB_PROMPT = (
    "Detect UI regions in this screenshot and return JSON only.\n"
    "Schema: "
    '{"rois":[{"id":"r1","kind":"window|pane|tabstrip|console|calendar|chat|email|browser|other","label":"text","bbox_norm":[x1,y1,x2,y2],"priority":0.0}],'
    '"windows":[{"label":"text","app":"text","context":"host|vdi|unknown","bbox_norm":[x1,y1,x2,y2],"visibility":"fully_visible|partially_occluded|unknown","z_hint":0.0}]}. '
    "Use normalized bbox values in [0,1], include diverse ROIs across the full image, and return only valid JSON."
)

DEFAULT_ROI_PROMPT = (
    "Parse this cropped UI region and return JSON only.\n"
    "Schema: "
    '{"elements":[{"type":"window|pane|button|row|cell|text|other","label":"text","bbox_norm":[x1,y1,x2,y2]}],'
    '"windows":[{"label":"text","app":"text","context":"host|vdi|unknown","bbox_norm":[x1,y1,x2,y2],"visibility":"fully_visible|partially_occluded|unknown","z_hint":0.0}],'
    '"facts":[{"key":"adv.* key","value":"visible text value","confidence":0.0}]}. '
    "Use canonical fact keys when visible (adv.window.*, adv.focus.*, adv.incident.*, adv.activity.*, adv.details.*, "
    "adv.calendar.*, adv.slack.*, adv.dev.*, adv.console.*, adv.browser.*). "
    "Use only visible evidence, valid normalized bboxes, and return valid JSON only."
)

DEFAULT_FACTPACK_PROMPT = (
    "Return JSON only.\n"
    "Schema: "
    '{"facts":[{"key":"adv.* key","value":"visible value","confidence":0.0}],'
    '"windows":[{"label":"text","app":"text","context":"host|vdi|unknown","bbox_norm":[x1,y1,x2,y2],"visibility":"fully_visible|partially_occluded|unknown","z_hint":0.0}]}. '
    "Extract high-fidelity canonical facts from visible UI only (no guessing). "
    "Preferred keys include: "
    "adv.window.count, adv.window.N.app/context/visibility/z_order, "
    "adv.focus.window, adv.focus.evidence_N_kind/text, "
    "adv.incident.subject/sender_display/sender_domain/action_buttons/button.complete_bbox_norm/button.view_details_bbox_norm, "
    "adv.activity.count/adv.activity.N.timestamp/text, "
    "adv.details.count/adv.details.N.label/value, "
    "adv.calendar.month_year/selected_date/item_count/item.N.start/item.N.title, "
    "adv.slack.dm_name/message_count/thumbnail_desc/msg.N.sender/timestamp/text, "
    "adv.dev.tests_cmd/what_changed_count/what_changed.N/file_count/file.N, "
    "adv.console.red_count/green_count/other_count/red_lines, "
    "adv.browser.window_count/browser.N.hostname/active_title/tab_count. "
    "If a value is not clearly visible, omit that key."
)

DEFAULT_TOPIC_FACTPACK_TOPICS = [
    "window",
    "focus",
    "incident",
    "activity",
    "details",
    "calendar",
    "slack",
    "dev",
    "console",
    "browser",
]

DEFAULT_TOPIC_FACTPACK_PROMPTS: dict[str, str] = {
    "window": (
        "Return JSON only with schema "
        '{"facts":[{"key":"adv.window.*","value":"text","confidence":0.0}],"windows":[{"label":"text","app":"text","context":"host|vdi|unknown","bbox_norm":[x1,y1,x2,y2],"visibility":"fully_visible|partially_occluded|unknown","z_hint":0.0}]}. '
        "Extract top-level visible windows and emit canonical keys: adv.window.count and adv.window.N.app/context/visibility/z_order. "
        "Use only visible evidence and omit unclear values."
    ),
    "focus": (
        "Return JSON only with schema "
        '{"facts":[{"key":"adv.focus.*","value":"text","confidence":0.0}]}. '
        "Extract focused window with two evidence items using keys adv.focus.window, adv.focus.evidence_1_kind/text, adv.focus.evidence_2_kind/text."
    ),
    "incident": (
        "Return JSON only with schema "
        '{"facts":[{"key":"adv.incident.*","value":"text","confidence":0.0}]}. '
        "Extract incident reading-pane fields using keys adv.incident.subject, adv.incident.sender_display, adv.incident.sender_domain, adv.incident.action_buttons. "
        "sender_domain must be domain only."
    ),
    "activity": (
        "Return JSON only with schema "
        '{"facts":[{"key":"adv.activity.*","value":"text","confidence":0.0}]}. '
        "Extract Record Activity timeline with adv.activity.count and adv.activity.N.timestamp/text in top-to-bottom order."
    ),
    "details": (
        "Return JSON only with schema "
        '{"facts":[{"key":"adv.details.*","value":"text","confidence":0.0}]}. '
        "Extract Details key-value rows with adv.details.count and adv.details.N.label/value."
    ),
    "calendar": (
        "Return JSON only with schema "
        '{"facts":[{"key":"adv.calendar.*","value":"text","confidence":0.0}]}. '
        "Extract calendar month/year, selected date, and visible schedule rows with adv.calendar.month_year, adv.calendar.selected_date, adv.calendar.item_count, adv.calendar.item.N.start/title."
    ),
    "slack": (
        "Return JSON only with schema "
        '{"facts":[{"key":"adv.slack.*","value":"text","confidence":0.0}]}. '
        "Extract Slack DM fields using adv.slack.dm_name, adv.slack.message_count, adv.slack.msg.N.sender/timestamp/text, adv.slack.thumbnail_desc."
    ),
    "dev": (
        "Return JSON only with schema "
        '{"facts":[{"key":"adv.dev.*","value":"text","confidence":0.0}]}. '
        "Extract dev summary fields using adv.dev.tests_cmd, adv.dev.what_changed_count, adv.dev.what_changed.N, adv.dev.file_count, adv.dev.file.N."
    ),
    "console": (
        "Return JSON only with schema "
        '{"facts":[{"key":"adv.console.*","value":"text","confidence":0.0}]}. '
        "Extract console color metrics with adv.console.red_count, adv.console.green_count, adv.console.other_count, adv.console.red_lines."
    ),
    "browser": (
        "Return JSON only with schema "
        '{"facts":[{"key":"adv.browser.*","value":"text","confidence":0.0}]}. '
        "Extract browser tuples with adv.browser.window_count and adv.browser.N.hostname/active_title/tab_count."
    ),
}


@dataclass(frozen=True)
class _Roi:
    roi_id: str
    kind: str
    label: str
    priority_bp: int
    bbox_px: tuple[int, int, int, int]


class VllmVLM(PluginBase):
    def __init__(self, plugin_id: str, context: PluginContext) -> None:
        super().__init__(plugin_id, context)
        cfg = context.config if isinstance(context.config, dict) else {}
        self._base_url_policy_error = ""
        try:
            self._base_url = enforce_external_vllm_base_url(cfg.get("base_url"))
        except Exception as exc:
            self._base_url = EXTERNAL_VLLM_BASE_URL
            self._base_url_policy_error = f"invalid_vllm_base_url:{type(exc).__name__}:{exc}"
        self._api_key = str(cfg.get("api_key") or "").strip() or None
        self._model = str(cfg.get("model") or "").strip() or None
        self._timeout_s = float(cfg.get("timeout_s") or 30.0)
        self._prompt = str(cfg.get("prompt") or DEFAULT_LAYOUT_PROMPT).strip()
        self._max_tokens = int(cfg.get("max_tokens") or 256)
        self._temperature = float(cfg.get("temperature") if "temperature" in cfg else 0.0)
        self._top_p = float(cfg.get("top_p") if "top_p" in cfg else 1.0)
        self._n = max(1, int(cfg.get("n") if "n" in cfg else 1))
        seed_raw = cfg.get("seed")
        self._seed: int | None = None
        if seed_raw is not None and str(seed_raw).strip() != "":
            try:
                self._seed = int(seed_raw)
            except Exception:
                self._seed = None
        self._two_pass_enabled = bool(cfg.get("two_pass_enabled", True))
        self._thumb_prompt = str(cfg.get("thumb_prompt") or DEFAULT_THUMB_PROMPT).strip()
        self._roi_prompt = str(cfg.get("roi_prompt") or DEFAULT_ROI_PROMPT).strip()
        self._thumb_max_px = max(512, int(cfg.get("thumb_max_px") or 960))
        self._max_rois = max(1, int(cfg.get("max_rois") or 8))
        self._grid_sections = max(1, min(24, int(cfg.get("grid_sections") or 8)))
        self._grid_enforced = bool(cfg.get("grid_enforced", True))
        self._roi_max_side = max(512, int(cfg.get("roi_max_side") or 2048))
        self._thumb_max_tokens = max(128, int(cfg.get("thumb_max_tokens") or 768))
        self._roi_max_tokens = max(128, int(cfg.get("roi_max_tokens") or 1536))
        self._factpack_enabled = bool(cfg.get("factpack_enabled", True))
        self._factpack_prompt = str(cfg.get("factpack_prompt") or DEFAULT_FACTPACK_PROMPT).strip()
        self._factpack_max_tokens = max(256, int(cfg.get("factpack_max_tokens") or 1536))
        self._topic_factpack_enabled = bool(cfg.get("topic_factpack_enabled", True))
        topics_raw = cfg.get("topic_factpack_topics")
        topics: list[str] = []
        if isinstance(topics_raw, list):
            topics = [str(x).strip().lower() for x in topics_raw if str(x).strip()]
        if not topics:
            topics = list(DEFAULT_TOPIC_FACTPACK_TOPICS)
        self._topic_factpack_topics = [x for x in topics if x in DEFAULT_TOPIC_FACTPACK_PROMPTS]
        default_topic_max = min(self._factpack_max_tokens, 1024)
        self._topic_factpack_max_tokens = max(128, int(cfg.get("topic_factpack_max_tokens") or default_topic_max))
        self._topic_factpack_min_topics = max(0, min(10, int(cfg.get("topic_factpack_min_topics") or 6)))
        self._max_retries = max(1, min(5, int(cfg.get("max_retries") or 3)))
        self._fail_open_after_errors = max(1, min(6, int(cfg.get("fail_open_after_errors") or 2)))
        self._failure_cooldown_s = max(5.0, float(cfg.get("failure_cooldown_s") or 45.0))
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._client: OpenAICompatClient | None = None
        self._last_chat_error = ""
        self._model_validated = False
        self._promptops = None
        self._promptops_cfg = cfg.get("promptops", {}) if isinstance(cfg.get("promptops", {}), dict) else {}
        if bool(self._promptops_cfg.get("enabled", True)):
            try:
                from autocapture.promptops.engine import PromptOpsLayer

                self._promptops = PromptOpsLayer(
                    {
                        "promptops": self._promptops_cfg,
                        "paths": {"data_dir": str(self._promptops_cfg.get("data_dir") or "data")},
                    }
                )
            except Exception:
                self._promptops = None

    def capabilities(self) -> dict[str, Any]:
        return {"vision.extractor": self}

    def extract(self, image_bytes: bytes) -> dict[str, Any]:
        payload: dict[str, Any] = {"layout": {"elements": [], "edges": []}, "backend": "unavailable", "text": ""}
        if not image_bytes:
            return payload
        if self._is_circuit_open():
            payload["model_error"] = "vlm_temporarily_unavailable:circuit_open"
            payload["circuit_open_until_s"] = float(self._circuit_open_until)
            return payload
        client = self._ensure_client(payload)
        if client is None:
            return payload
        self._resolve_model(client)
        if not self._model:
            payload["model_error"] = "vlm_model_missing"
            return payload
        if self._two_pass_enabled and _PIL_AVAILABLE:
            two_pass = self._run_two_pass(client, image_bytes)
            layout = two_pass.get("layout", {}) if isinstance(two_pass.get("layout", {}), dict) else {}
            elements = layout.get("elements", []) if isinstance(layout.get("elements", []), list) else []
            ui_state = layout.get("ui_state", {}) if isinstance(layout.get("ui_state", {}), dict) else {}
            has_structured = bool(
                (isinstance(ui_state.get("windows"), list) and len(ui_state.get("windows", [])) > 0)
                or (isinstance(ui_state.get("facts"), list) and len(ui_state.get("facts", [])) > 0)
            )
            if _valid_layout(layout) and (len(elements) >= 2 or has_structured):
                payload.update(two_pass)
                return payload
        # Fallback to single-pass layout extraction.
        single = self._run_single_pass(client, image_bytes)
        payload.update(single)
        return payload

    def _ensure_client(self, payload: dict[str, Any]) -> OpenAICompatClient | None:
        if self._client is not None:
            return self._client
        if self._base_url_policy_error:
            payload["model_error"] = self._base_url_policy_error
            return None
        try:
            self._client = OpenAICompatClient(
                base_url=self._base_url,
                api_key=self._api_key,
                timeout_s=self._timeout_s,
            )
        except Exception as exc:
            payload["model_error"] = f"client_init_failed:{type(exc).__name__}:{exc}"
            self._client = None
        return self._client

    def _run_single_pass(self, client: OpenAICompatClient, image_bytes: bytes) -> dict[str, Any]:
        out: dict[str, Any] = {"layout": {"elements": [], "edges": []}, "backend": "unavailable", "text": ""}
        content = self._chat_image(
            client,
            image_bytes,
            self._prompt,
            max_tokens=self._max_tokens,
            prompt_id="vlm.single_pass.layout",
            metadata={"pass": "single"},
        )
        if not content:
            detail = str(self._last_chat_error or "").strip()
            out["model_error"] = f"vlm_empty_response:{detail}" if detail else "vlm_empty_response"
            return out
        layout = _extract_layout_from_text(content)
        if _valid_layout(layout):
            layout = dict(layout)
            layout.setdefault("edges", [])
            layout["state_id"] = "vlm"
            source_backend = str(layout.get("source_backend") or "openai_compat_layout").strip() or "openai_compat_layout"
            layout["source_backend"] = source_backend
            layout["source_provider_id"] = self.plugin_id
            out["backend"] = source_backend
            out["layout"] = layout
            out["text"] = json.dumps(layout, sort_keys=True, separators=(",", ":"))
            out["model_id"] = self._model
            return out
        out["backend"] = "openai_compat_unparsed"
        out["text_plain"] = content
        out["model_error"] = "vlm_layout_parse_failed"
        return out

    def _run_two_pass(self, client: OpenAICompatClient, image_bytes: bytes) -> dict[str, Any]:
        out: dict[str, Any] = {"layout": {"elements": [], "edges": []}, "backend": "unavailable", "text": ""}
        try:
            image = Image.open(BytesIO(image_bytes)).convert("RGB")  # type: ignore[arg-type]
        except Exception as exc:
            out["model_error"] = f"image_decode_failed:{type(exc).__name__}:{exc}"
            return out

        thumb = _make_thumbnail(image, max_width=self._thumb_max_px)
        thumb_bytes = _encode_png(thumb)
        thumb_content = self._chat_image(
            client,
            thumb_bytes,
            self._thumb_prompt,
            max_tokens=self._thumb_max_tokens,
            prompt_id="vlm.two_pass.thumb",
            metadata={"pass": "thumb"},
        )
        if not thumb_content:
            detail = str(self._last_chat_error or "").strip()
            out["model_error"] = f"vlm_two_pass_thumb_empty:{detail}" if detail else "vlm_two_pass_thumb_empty"
            return out
        thumb_json = _extract_layout_from_text(thumb_content)

        rois = _collect_rois(
            thumb_json,
            width=int(image.width),
            height=int(image.height),
            max_rois=self._max_rois,
            grid_sections=self._grid_sections,
            grid_enforced=self._grid_enforced,
        )
        windows = _parse_windows(thumb_json, width=int(image.width), height=int(image.height), parent_roi=None)
        layout_elements: list[dict[str, Any]] = []
        facts: list[dict[str, Any]] = []
        roi_reports: list[dict[str, Any]] = []

        for roi in rois:
            if self._is_circuit_open():
                break
            if self._grid_enforced and roi.roi_id == "full":
                # Full-frame context is handled by factpack/topic-factpack.
                # Skip duplicate full ROI parsing when deterministic grid map/reduce is enabled.
                continue
            crop = image.crop(roi.bbox_px)
            if max(crop.width, crop.height) > self._roi_max_side:
                scale = float(self._roi_max_side) / float(max(crop.width, crop.height))
                crop = crop.resize((max(1, int(round(crop.width * scale))), max(1, int(round(crop.height * scale)))))
            crop_bytes = _encode_png(crop)
            roi_content = self._chat_image(
                client,
                crop_bytes,
                self._roi_prompt,
                max_tokens=self._roi_max_tokens,
                prompt_id="vlm.two_pass.roi",
                metadata={"pass": "roi", "roi_id": roi.roi_id, "roi_kind": roi.kind},
            )
            roi_json = _extract_layout_from_text(roi_content)
            roi_reports.append(
                {
                    "id": roi.roi_id,
                    "kind": roi.kind,
                    "source": ("grid" if str(roi.roi_id).startswith("grid_") else ("full" if roi.roi_id == "full" else "model")),
                    "label": roi.label,
                    "priority_bp": int(roi.priority_bp),
                    "bbox_px": list(roi.bbox_px),
                    "raw_ok": isinstance(roi_json, dict),
                }
            )
            if not isinstance(roi_json, dict):
                continue
            layout_elements.extend(_parse_elements(roi_json, parent_roi=roi))
            windows.extend(_parse_windows(roi_json, width=int(image.width), height=int(image.height), parent_roi=roi))
            facts.extend(_parse_facts(roi_json, parent_roi=roi))

        full_roi = rois[0] if rois else _Roi("full", "window", "full_image", 10000, (0, 0, int(image.width), int(image.height)))
        if self._factpack_enabled:
            if self._is_circuit_open():
                self._last_chat_error = "vlm_circuit_open_factpack_skipped"
            else:
                factpack_content = self._chat_image(
                    client,
                    image_bytes,
                    self._factpack_prompt,
                    max_tokens=self._factpack_max_tokens,
                    prompt_id="vlm.two_pass.factpack",
                    metadata={"pass": "factpack"},
                )
                factpack_json = _extract_layout_from_text(factpack_content)
                if isinstance(factpack_json, dict):
                    windows.extend(_parse_windows(factpack_json, width=int(image.width), height=int(image.height), parent_roi=None))
                    facts.extend(_parse_facts(factpack_json, parent_roi=full_roi))
        if self._topic_factpack_enabled:
            present_topics = _adv_fact_topics(facts)
            missing_topics = [topic for topic in self._topic_factpack_topics if topic not in present_topics]
            if len(present_topics) < self._topic_factpack_min_topics:
                for topic in missing_topics:
                    if self._is_circuit_open():
                        break
                    topic_prompt = DEFAULT_TOPIC_FACTPACK_PROMPTS.get(topic, "")
                    if not topic_prompt:
                        continue
                    topic_content = self._chat_image(
                        client,
                        image_bytes,
                        topic_prompt,
                        max_tokens=self._topic_factpack_max_tokens,
                        prompt_id=f"vlm.two_pass.factpack.{topic}",
                        metadata={"pass": "factpack_topic", "topic": topic},
                    )
                    topic_json = _extract_layout_from_text(topic_content)
                    if not isinstance(topic_json, dict):
                        continue
                    windows.extend(_parse_windows(topic_json, width=int(image.width), height=int(image.height), parent_roi=None))
                    facts.extend(_parse_facts(topic_json, parent_roi=full_roi))

        # Include window-level elements for better observation graph coverage.
        for win in _dedupe_windows(windows):
            layout_elements.append(
                {
                    "type": "window",
                    "bbox": list(win["bbox"]),
                    "text": str(win.get("label") or win.get("app") or "").strip(),
                    "interactable": False,
                    "state": {},
                    "children": [],
                }
            )
        layout_elements = _dedupe_elements(layout_elements)
        processed_reports = [item for item in roi_reports if isinstance(item, dict)]
        processed_count = len(processed_reports)
        failed_count = len([item for item in processed_reports if not bool(item.get("raw_ok"))])
        grid_count = len([item for item in processed_reports if str(item.get("source") or "") == "grid"])
        coverage_bp = _roi_coverage_bp(
            [tuple(item.bbox_px) for item in rois if isinstance(item, _Roi)],
            width=int(image.width),
            height=int(image.height),
        )
        ui_state = {
            "schema_version": 1,
            "image_size": [int(image.width), int(image.height)],
            "rois": [_roi_to_dict(item) for item in rois],
            "windows": _dedupe_windows(windows),
            "facts": _dedupe_facts(facts),
            "roi_reports": roi_reports,
            "map_reduce": {
                "grid_sections": int(self._grid_sections),
                "grid_enforced": bool(self._grid_enforced),
                "roi_total": int(len(rois)),
                "roi_processed": int(processed_count),
                "roi_failed": int(failed_count),
                "grid_roi_processed": int(grid_count),
                "coverage_bp": int(coverage_bp),
            },
        }
        layout = {
            "elements": layout_elements,
            "edges": [],
            "state_id": "vlm",
            "source_backend": "openai_compat_two_pass",
            "source_provider_id": self.plugin_id,
            "ui_state": ui_state,
        }
        out["backend"] = "openai_compat_two_pass"
        out["layout"] = layout
        out["text"] = json.dumps(
            {
                "elements": layout_elements,
                "windows": ui_state.get("windows", []),
                "facts": ui_state.get("facts", []),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        out["model_id"] = self._model
        out["ui_state"] = ui_state
        if not layout_elements:
            detail = str(self._last_chat_error or "").strip()
            out["model_error"] = f"vlm_two_pass_empty:{detail}" if detail else "vlm_two_pass_empty"
        return out

    def _is_circuit_open(self) -> bool:
        if float(self._circuit_open_until) <= 0.0:
            return False
        if time.perf_counter() < float(self._circuit_open_until):
            return True
        self._circuit_open_until = 0.0
        return False

    def _mark_chat_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def _mark_chat_failure(self, reason: str) -> None:
        _ = reason
        self._consecutive_failures = int(self._consecutive_failures) + 1
        if int(self._consecutive_failures) >= int(self._fail_open_after_errors):
            self._circuit_open_until = float(time.perf_counter()) + float(self._failure_cooldown_s)

    def _chat_image(
        self,
        client: OpenAICompatClient,
        image_bytes: bytes,
        prompt: str,
        *,
        max_tokens: int,
        prompt_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        started = time.perf_counter()
        if self._is_circuit_open():
            self._last_chat_error = "vlm_circuit_open"
            return ""
        if not self._model:
            self._last_chat_error = "model_missing"
            self._mark_chat_failure(self._last_chat_error)
            self._record_promptops_interaction(
                prompt_id=prompt_id,
                prompt_input=prompt,
                prompt_effective=prompt,
                response_text="",
                success=False,
                latency_ms=float((time.perf_counter() - started) * 1000.0),
                error="model_missing",
                metadata=metadata,
            )
            return ""
        self._last_chat_error = ""
        current = bytes(image_bytes or b"")
        prompt_effective = prompt
        promptops_meta: dict[str, Any] = {
            "used": bool(self._promptops is not None),
            "applied": False,
            "strategy": str(self._promptops_cfg.get("model_strategy", "model_contract")),
        }
        if self._promptops is not None:
            try:
                strategy = str(self._promptops_cfg.get("model_strategy", "model_contract"))
                p = self._promptops.prepare_prompt(
                    prompt,
                    prompt_id=str(prompt_id),
                    strategy=strategy,
                    persist=bool(self._promptops_cfg.get("persist_prompts", False)),
                )
                prompt_effective = p.prompt
                promptops_meta["applied"] = bool(p.applied)
            except Exception:
                pass
        max_retries = int(self._max_retries)
        for attempt_idx in range(max_retries):
            req: dict[str, Any] = {
                "model": self._model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_effective},
                            {"type": "image_url", "image_url": {"url": image_bytes_to_data_url(current, content_type="image/png")}},
                        ],
                    }
                ],
                "temperature": float(self._temperature),
                "top_p": float(self._top_p),
                "n": int(self._n),
                "max_tokens": int(max_tokens),
            }
            if self._seed is not None:
                req["seed"] = int(self._seed)
            try:
                resp = client.chat_completions(req)
            except Exception as exc:
                msg = str(exc or "").casefold()
                timeout_error = _is_timeout_error(msg)
                retryable_server_error = (
                    "http_error:500" in msg
                    or "internal server error" in msg
                    or "http_error:502" in msg
                    or "http_error:503" in msg
                    or "http_error:504" in msg
                    or "http_error:429" in msg
                    or "rate limit" in msg
                )
                if _is_model_not_found_error(msg):
                    previous = str(self._model or "").strip()
                    self._model_validated = False
                    self._resolve_model(client)
                    if self._model and str(self._model).strip() and str(self._model).strip() != previous:
                        self._last_chat_error = f"model_fallback:{previous}->{self._model}"
                        continue
                if _is_context_limit_error(msg) or timeout_error:
                    downsized = _downscale_png_bytes(current)
                    if downsized and len(downsized) < len(current):
                        current = downsized
                        self._last_chat_error = (
                            "timeout_downscaled_retry" if timeout_error else "context_limit_downscaled_retry"
                        )
                        continue
                if (retryable_server_error or timeout_error) and (attempt_idx + 1 < max_retries):
                    self._last_chat_error = str(exc or "chat_exception").strip()[:240]
                    if not self._last_chat_error:
                        self._last_chat_error = "chat_retryable_error"
                    # Retry transient HTTP/timeout failures before opening the circuit.
                    # Image payload may already have been downscaled above.
                    continue
                if _is_context_limit_error(msg) and (attempt_idx + 1 < max_retries):
                    downsized = _downscale_png_bytes(current)
                    if downsized and len(downsized) < len(current):
                        current = downsized
                        self._last_chat_error = "context_limit_downscaled_retry"
                        continue
                self._last_chat_error = str(exc or "chat_exception").strip()[:240]
                self._mark_chat_failure(self._last_chat_error)
                self._record_promptops_interaction(
                    prompt_id=prompt_id,
                    prompt_input=prompt,
                    prompt_effective=prompt_effective,
                    response_text="",
                    success=False,
                    latency_ms=float((time.perf_counter() - started) * 1000.0),
                    error=str(self._last_chat_error or "chat_exception"),
                    metadata=self._merge_promptops_meta(metadata, promptops_meta),
                )
                return ""
            choices = resp.get("choices", [])
            if not isinstance(choices, list) or not choices:
                self._last_chat_error = "empty_choices"
                self._mark_chat_failure(self._last_chat_error)
                self._record_promptops_interaction(
                    prompt_id=prompt_id,
                    prompt_input=prompt,
                    prompt_effective=prompt_effective,
                    response_text="",
                    success=False,
                    latency_ms=float((time.perf_counter() - started) * 1000.0),
                    error="empty_choices",
                    metadata=self._merge_promptops_meta(metadata, promptops_meta),
                )
                return ""
            msg = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            content = str(msg.get("content") or "").strip()
            if content:
                self._last_chat_error = ""
                self._mark_chat_success()
                self._record_promptops_interaction(
                    prompt_id=prompt_id,
                    prompt_input=prompt,
                    prompt_effective=prompt_effective,
                    response_text=content,
                    success=True,
                    latency_ms=float((time.perf_counter() - started) * 1000.0),
                    error="",
                    metadata=self._merge_promptops_meta(metadata, promptops_meta),
                )
                return content
            downsized = _downscale_png_bytes(current)
            if downsized and len(downsized) < len(current):
                current = downsized
                self._last_chat_error = "empty_content_downscaled_retry"
                continue
            self._last_chat_error = "empty_content"
            self._mark_chat_failure(self._last_chat_error)
            self._record_promptops_interaction(
                prompt_id=prompt_id,
                prompt_input=prompt,
                prompt_effective=prompt_effective,
                response_text="",
                success=False,
                latency_ms=float((time.perf_counter() - started) * 1000.0),
                error="empty_content",
                metadata=self._merge_promptops_meta(metadata, promptops_meta),
            )
            return ""
        self._last_chat_error = "max_retries_exhausted"
        self._mark_chat_failure(self._last_chat_error)
        self._record_promptops_interaction(
            prompt_id=prompt_id,
            prompt_input=prompt,
            prompt_effective=prompt_effective,
            response_text="",
            success=False,
            latency_ms=float((time.perf_counter() - started) * 1000.0),
            error="max_retries_exhausted",
            metadata=self._merge_promptops_meta(metadata, promptops_meta),
        )
        return ""

    def _merge_promptops_meta(self, metadata: dict[str, Any] | None, promptops_meta: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        if isinstance(metadata, dict) and metadata:
            merged.update(metadata)
        merged["promptops"] = dict(promptops_meta)
        return merged

    def _record_promptops_interaction(
        self,
        *,
        prompt_id: str,
        prompt_input: str,
        prompt_effective: str,
        response_text: str,
        success: bool,
        latency_ms: float,
        error: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        if self._promptops is None:
            return
        try:
            self._promptops.record_model_interaction(
                prompt_id=str(prompt_id),
                provider_id=self.plugin_id,
                model=str(self._model or ""),
                prompt_input=str(prompt_input or ""),
                prompt_effective=str(prompt_effective or ""),
                response_text=str(response_text or ""),
                success=bool(success),
                latency_ms=float(latency_ms),
                error=str(error or ""),
                metadata=metadata if isinstance(metadata, dict) else {},
            )
        except Exception:
            return

    @staticmethod
    def _discover_model(client: OpenAICompatClient) -> str | None:
        ids = VllmVLM._discover_model_ids(client)
        return ids[0] if ids else None

    @staticmethod
    def _discover_model_ids(client: OpenAICompatClient) -> list[str]:
        try:
            models = client.list_models()
        except Exception:
            return []
        data = models.get("data", []) if isinstance(models, dict) else []
        if not isinstance(data, list):
            return []
        out: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if model_id:
                out.append(model_id)
        return out

    def _resolve_model(self, client: OpenAICompatClient) -> str | None:
        if self._model and self._model_validated:
            return self._model
        model_ids = self._discover_model_ids(client)
        if not model_ids:
            return self._model
        if self._model and self._model in model_ids:
            self._model_validated = True
            return self._model
        self._model = model_ids[0]
        self._model_validated = True
        return self._model


def create_plugin(plugin_id: str, context: PluginContext) -> VllmVLM:
    return VllmVLM(plugin_id, context)


def _extract_layout_from_text(content: str) -> dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {}
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    candidates = [match.group(1)] if match else []
    candidates.append(text)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        blob = text[start : end + 1]
        try:
            parsed = json.loads(blob)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    recovered = _recover_layout_from_partial_json(text)
    if recovered:
        return recovered
    return {}


_PARTIAL_ELEMENT_RE = re.compile(
    r'"type"\s*:\s*"(?P<type>[^"]+)"(?P<mid>.{0,640}?)"bbox"\s*:\s*\[(?P<bbox>[^\]]+)\](?P<tail>.{0,640})',
    flags=re.IGNORECASE | re.DOTALL,
)


def _recover_layout_from_partial_json(text: str) -> dict[str, Any]:
    blob = str(text or "")
    if not blob:
        return {}
    elements: list[dict[str, Any]] = []
    for match in _PARTIAL_ELEMENT_RE.finditer(blob):
        element_type = _clean_text(match.group("type")).casefold() or "other"
        if element_type in {"", "null"}:
            continue
        bbox_values = _parse_bbox_values(match.group("bbox") or "")
        if bbox_values is None:
            continue
        snippet = f"{match.group('mid') or ''}{match.group('tail') or ''}"
        label = ""
        m_text = re.search(r'"text"\s*:\s*"([^"]{1,180})"', snippet, flags=re.IGNORECASE)
        if m_text:
            label = _clean_text(m_text.group(1))
        if not label:
            m_label = re.search(r'"label"\s*:\s*"([^"]{1,180})"', snippet, flags=re.IGNORECASE)
            if m_label:
                label = _clean_text(m_label.group(1))
        elements.append(
            {
                "type": element_type,
                "bbox": [float(bbox_values[0]), float(bbox_values[1]), float(bbox_values[2]), float(bbox_values[3])],
                "text": label,
                "interactable": bool(element_type in {"button", "textbox", "checkbox", "radio", "dropdown", "tab", "menu", "icon"}),
                "state": {"enabled": True, "selected": False, "focused": False, "expanded": False},
                "children": [],
            }
        )
        if len(elements) >= 64:
            break
    rois: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []

    for m in re.finditer(
        r'"id"\s*:\s*"(?P<id>[^"]+)"(?P<mid>.{0,300}?)"kind"\s*:\s*"(?P<kind>[^"]+)"(?P<tail>.{0,500}?)"bbox_norm"\s*:\s*\[(?P<bbox>[^\]]+)\]',
        blob,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        bbox_values = _parse_bbox_values(m.group("bbox") or "")
        if bbox_values is None:
            continue
        label_match = re.search(r'"label"\s*:\s*"([^"]{1,120})"', f"{m.group('mid')}{m.group('tail')}", flags=re.IGNORECASE)
        pri_match = re.search(r'"priority"\s*:\s*(-?\d+(?:\.\d+)?)', f"{m.group('mid')}{m.group('tail')}", flags=re.IGNORECASE)
        rois.append(
            {
                "id": _clean_text(m.group("id")),
                "kind": _clean_text(m.group("kind")),
                "label": _clean_text(label_match.group(1) if label_match else ""),
                "bbox_norm": [bbox_values[0], bbox_values[1], bbox_values[2], bbox_values[3]],
                "priority": float(pri_match.group(1)) if pri_match else 0.0,
            }
        )
        if len(rois) >= 32:
            break

    for m in re.finditer(
        r'"label"\s*:\s*"(?P<label>[^"]{1,160})"(?P<mid>.{0,500}?)"app"\s*:\s*"(?P<app>[^"]{1,160})"(?P<tail>.{0,500}?)"bbox_norm"\s*:\s*\[(?P<bbox>[^\]]+)\]',
        blob,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        bbox_values = _parse_bbox_values(m.group("bbox") or "")
        if bbox_values is None:
            continue
        side = f"{m.group('mid')}{m.group('tail')}"
        ctx = re.search(r'"context"\s*:\s*"([^"]+)"', side, flags=re.IGNORECASE)
        vis = re.search(r'"visibility"\s*:\s*"([^"]+)"', side, flags=re.IGNORECASE)
        z = re.search(r'"z_hint"\s*:\s*(-?\d+(?:\.\d+)?)', side, flags=re.IGNORECASE)
        windows.append(
            {
                "label": _clean_text(m.group("label")),
                "app": _clean_text(m.group("app")),
                "context": _clean_text(ctx.group(1) if ctx else "unknown"),
                "bbox_norm": [bbox_values[0], bbox_values[1], bbox_values[2], bbox_values[3]],
                "visibility": _clean_text(vis.group(1) if vis else "unknown"),
                "z_hint": float(z.group(1)) if z else 0.0,
            }
        )
        if len(windows) >= 32:
            break

    for m in re.finditer(
        r'"key"\s*:\s*"(?P<key>[^"]{1,180})"(?P<mid>.{0,300}?)"value"\s*:\s*"(?P<value>[^"]{1,400})"(?P<tail>.{0,120})',
        blob,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        side = f"{m.group('mid')}{m.group('tail')}"
        conf = re.search(r'"confidence"\s*:\s*(-?\d+(?:\.\d+)?)', side, flags=re.IGNORECASE)
        facts.append(
            {
                "key": _clean_text(m.group("key")),
                "value": _clean_text(m.group("value")),
                "confidence": float(conf.group(1)) if conf else 0.7,
            }
        )
        if len(facts) >= 128:
            break

    if len(elements) < 1 and len(rois) < 1 and len(windows) < 1 and len(facts) < 1:
        return {}
    out: dict[str, Any] = {"edges": [], "state_id": "vlm", "source_backend": "openai_compat_text_recovered"}
    if elements:
        out["elements"] = elements
    if rois:
        out["rois"] = rois
    if windows:
        out["windows"] = windows
    if facts:
        out["facts"] = facts
    return out


def _parse_bbox_values(raw_bbox: str) -> tuple[float, float, float, float] | None:
    nums = re.findall(r"-?\d+(?:\.\d+)?", str(raw_bbox or ""))
    if len(nums) < 4:
        return None
    try:
        x1, y1, x2, y2 = (float(nums[0]), float(nums[1]), float(nums[2]), float(nums[3]))
    except Exception:
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _valid_layout(layout: dict[str, Any]) -> bool:
    if not isinstance(layout, dict):
        return False
    elements = layout.get("elements")
    return isinstance(elements, list)


def _make_thumbnail(image: Any, *, max_width: int) -> Any:
    width = int(getattr(image, "width", 0) or 0)
    height = int(getattr(image, "height", 0) or 0)
    if width <= 0 or height <= 0 or width <= max_width:
        return image
    scale = float(max_width) / float(width)
    return image.resize((int(max_width), max(1, int(round(height * scale)))))


def _is_context_limit_error(message: str) -> bool:
    text = str(message or "").casefold()
    return (
        "decoder prompt" in text
        or "maximum model length" in text
        or "max model length" in text
        or "context length" in text
        or "too many tokens" in text
    )


def _is_timeout_error(message: str) -> bool:
    text = str(message or "").casefold()
    return (
        "timed out" in text
        or "timeout" in text
        or "read timed out" in text
        or "deadline exceeded" in text
    )


def _is_model_not_found_error(message: str) -> bool:
    text = str(message or "").casefold()
    return ("model" in text and "not found" in text) or ("model" in text and "does not exist" in text)


def _downscale_png_bytes(image_bytes: bytes) -> bytes | None:
    if not _PIL_AVAILABLE:
        return None
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")  # type: ignore[arg-type]
    except Exception:
        return None
    w = int(getattr(img, "width", 0) or 0)
    h = int(getattr(img, "height", 0) or 0)
    if w <= 0 or h <= 0:
        return None
    longest = max(w, h)
    if longest <= 512:
        return None
    scale = 0.75
    nw = max(256, int(round(float(w) * scale)))
    nh = max(256, int(round(float(h) * scale)))
    resized = img.resize((nw, nh))
    return _encode_png(resized)


def _encode_png(image: Any) -> bytes:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _roi_to_dict(roi: _Roi) -> dict[str, Any]:
    return {
        "id": roi.roi_id,
        "kind": roi.kind,
        "label": roi.label,
        "priority_bp": int(roi.priority_bp),
        "bbox_px": [int(roi.bbox_px[0]), int(roi.bbox_px[1]), int(roi.bbox_px[2]), int(roi.bbox_px[3])],
    }


def _norm_bbox_to_px(raw: Any, *, width: int, height: int) -> tuple[int, int, int, int] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])
    except Exception:
        return None
    if x1 < 0.0 or y1 < 0.0 or x2 > 1.0 or y2 > 1.0 or x2 <= x1 or y2 <= y1:
        return None
    px1 = int(max(0, min(width, round(x1 * float(width)))))
    py1 = int(max(0, min(height, round(y1 * float(height)))))
    px2 = int(max(0, min(width, round(x2 * float(width)))))
    py2 = int(max(0, min(height, round(y2 * float(height)))))
    if px2 <= px1 or py2 <= py1:
        return None
    return (px1, py1, px2, py2)


def _roi_w(roi: _Roi) -> int:
    return int(max(1, roi.bbox_px[2] - roi.bbox_px[0]))


def _roi_h(roi: _Roi) -> int:
    return int(max(1, roi.bbox_px[3] - roi.bbox_px[1]))


def _to_bp(value: Any, *, default_bp: int) -> int:
    try:
        num = float(value)
    except Exception:
        return int(default_bp)
    if num <= 1.0:
        num *= 10000.0
    return int(max(0.0, min(10000.0, num)))


def _clean_text(value: Any) -> str:
    text = str(value or "").strip().replace("\u2019", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _enum_or_default(value: Any, allowed: set[str], default: str) -> str:
    low = str(value or "").strip().casefold()
    return low if low in allowed else default


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = float(iw * ih)
    if inter <= 0.0:
        return 0.0
    area_a = float(max(1, (ax2 - ax1) * (ay2 - ay1)))
    area_b = float(max(1, (bx2 - bx1) * (by2 - by1)))
    union = max(1.0, area_a + area_b - inter)
    return inter / union


def _grid_roi_specs(sections: int) -> list[tuple[str, tuple[float, float, float, float]]]:
    n = max(0, int(sections))
    if n <= 0:
        return []
    # Deterministic wide-screen defaults for 7680x2160 workflows.
    if n == 8:
        cols = 4
        rows = 2
    else:
        rows = 2 if n >= 4 else 1
        cols = int(math.ceil(float(n) / float(rows)))
    out: list[tuple[str, tuple[float, float, float, float]]] = []
    idx = 1
    for ry in range(rows):
        y1 = float(ry) / float(rows)
        y2 = float(ry + 1) / float(rows)
        for cx in range(cols):
            if idx > n:
                break
            x1 = float(cx) / float(cols)
            x2 = float(cx + 1) / float(cols)
            out.append((f"grid_{idx}", (x1, y1, x2, y2)))
            idx += 1
    return out


def _collect_rois(
    raw: dict[str, Any],
    *,
    width: int,
    height: int,
    max_rois: int,
    grid_sections: int = 8,
    grid_enforced: bool = False,
) -> list[_Roi]:
    full = _Roi("full", "window", "full_image", 10000, (0, 0, int(width), int(height)))
    out: list[_Roi] = [full]
    rois = raw.get("rois", []) if isinstance(raw.get("rois"), list) else []
    for idx, item in enumerate(rois, start=1):
        if not isinstance(item, dict):
            continue
        bbox = _norm_bbox_to_px(item.get("bbox_norm"), width=width, height=height)
        if bbox is None:
            continue
        out.append(
            _Roi(
                roi_id=str(item.get("id") or f"roi_{idx}"),
                kind=_clean_text(item.get("kind")) or "other",
                label=_clean_text(item.get("label")),
                priority_bp=_to_bp(item.get("priority"), default_bp=6000),
                bbox_px=bbox,
            )
        )
    out.sort(key=lambda r: (-int(r.priority_bp), r.roi_id))
    dedup: list[_Roi] = [full]
    fallback_specs = _grid_roi_specs(grid_sections)
    if grid_enforced:
        # Guarantee map/reduce over all grid chunks, then spend remaining
        # budget on model-proposed ROIs.
        target_cap = max(int(max_rois), 1 + len(fallback_specs))
        model_cap = max(0, int(target_cap) - 1 - len(fallback_specs))
    else:
        # Legacy behavior: reserve only a subset of room for coverage ROIs.
        reserve = min(4, len(fallback_specs))
        model_cap = max(1, int(max_rois) - 1 - reserve)
    for roi in out:
        if roi.roi_id == "full":
            continue
        keep = True
        for existing in dedup:
            if _iou(roi.bbox_px, existing.bbox_px) >= 0.9:
                keep = False
                break
        if keep:
            dedup.append(roi)
        if len(dedup) >= int(model_cap) + 1:
            break
    # Coverage backstop: add deterministic grid ROIs so high-res pass scans
    # the full desktop, even when model-proposed ROIs are concentrated.
    for roi_id, norm in fallback_specs:
        if (not grid_enforced) and len(dedup) >= int(max_rois):
            break
        bbox = _norm_bbox_to_px(norm, width=width, height=height)
        if bbox is None:
            continue
        candidate = _Roi(roi_id=roi_id, kind="pane", label=roi_id, priority_bp=4500, bbox_px=bbox)
        keep = True
        for existing in dedup:
            if _iou(candidate.bbox_px, existing.bbox_px) >= 0.92:
                keep = False
                break
        if not keep:
            continue
        dedup.append(candidate)
    if not grid_enforced:
        return dedup[: max(1, int(max_rois))]
    return dedup


def _roi_coverage_bp(boxes: list[tuple[int, int, int, int]], *, width: int, height: int) -> int:
    if width <= 0 or height <= 0:
        return 0
    clean: list[tuple[int, int, int, int]] = []
    for box in boxes:
        if not isinstance(box, tuple) or len(box) != 4:
            continue
        x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])
        if x2 <= x1 or y2 <= y1:
            continue
        x1 = max(0, min(width, x1))
        y1 = max(0, min(height, y1))
        x2 = max(0, min(width, x2))
        y2 = max(0, min(height, y2))
        if x2 <= x1 or y2 <= y1:
            continue
        clean.append((x1, y1, x2, y2))
    if not clean:
        return 0
    xs = sorted({x1 for x1, _, x2, _ in clean} | {x2 for _, _, x2, _ in clean})
    if len(xs) <= 1:
        return 0
    area = 0
    for idx in range(len(xs) - 1):
        sx1 = xs[idx]
        sx2 = xs[idx + 1]
        if sx2 <= sx1:
            continue
        intervals: list[tuple[int, int]] = []
        for x1, y1, x2, y2 in clean:
            if x1 < sx2 and x2 > sx1:
                intervals.append((y1, y2))
        if not intervals:
            continue
        intervals.sort(key=lambda item: (item[0], item[1]))
        merged: list[tuple[int, int]] = []
        cy1, cy2 = intervals[0]
        for ny1, ny2 in intervals[1:]:
            if ny1 <= cy2:
                cy2 = max(cy2, ny2)
            else:
                merged.append((cy1, cy2))
                cy1, cy2 = ny1, ny2
        merged.append((cy1, cy2))
        covered_y = sum(max(0, y2 - y1) for y1, y2 in merged)
        area += max(0, sx2 - sx1) * covered_y
    total = max(1, int(width) * int(height))
    bp = int(round((float(area) / float(total)) * 10000.0))
    return max(0, min(10000, bp))


def _parse_elements(raw: dict[str, Any], *, parent_roi: _Roi) -> list[dict[str, Any]]:
    entries = raw.get("elements", []) if isinstance(raw.get("elements"), list) else []
    out: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        local = _norm_bbox_to_px(entry.get("bbox_norm"), width=_roi_w(parent_roi), height=_roi_h(parent_roi))
        if local is None:
            continue
        gx1 = int(parent_roi.bbox_px[0] + local[0])
        gy1 = int(parent_roi.bbox_px[1] + local[1])
        gx2 = int(parent_roi.bbox_px[0] + local[2])
        gy2 = int(parent_roi.bbox_px[1] + local[3])
        label = _clean_text(entry.get("text")) or _clean_text(entry.get("label"))
        if not label:
            continue
        state = entry.get("state") if isinstance(entry.get("state"), dict) else {}
        interactable = bool(entry.get("interactable", False))
        el_type = _clean_text(entry.get("type")) or "other"
        out.append(
            {
                "type": el_type,
                "bbox": [gx1, gy1, gx2, gy2],
                "text": label,
                "interactable": interactable,
                "state": {
                    "enabled": bool(state.get("enabled", True)),
                    "selected": bool(state.get("selected", False)),
                    "focused": bool(state.get("focused", False)),
                    "expanded": bool(state.get("expanded", False)),
                },
                "children": [],
            }
        )
    return out


def _parse_windows(
    raw: dict[str, Any],
    *,
    width: int,
    height: int,
    parent_roi: _Roi | None,
) -> list[dict[str, Any]]:
    entries = raw.get("windows", []) if isinstance(raw.get("windows"), list) else []
    out: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        if parent_roi is None:
            bbox = _norm_bbox_to_px(entry.get("bbox_norm"), width=width, height=height)
        else:
            local = _norm_bbox_to_px(entry.get("bbox_norm"), width=_roi_w(parent_roi), height=_roi_h(parent_roi))
            if local is None:
                bbox = None
            else:
                bbox = (
                    int(parent_roi.bbox_px[0] + local[0]),
                    int(parent_roi.bbox_px[1] + local[1]),
                    int(parent_roi.bbox_px[0] + local[2]),
                    int(parent_roi.bbox_px[1] + local[3]),
                )
        if bbox is None:
            continue
        out.append(
            {
                "window_id": f"{parent_roi.roi_id if parent_roi else 'thumb'}:w:{idx}",
                "label": _clean_text(entry.get("label")),
                "app": _clean_text(entry.get("app")) or _clean_text(entry.get("label")),
                "context": _enum_or_default(entry.get("context"), {"host", "vdi", "unknown"}, "unknown"),
                "visibility": _enum_or_default(
                    entry.get("visibility"),
                    {"fully_visible", "partially_occluded", "unknown"},
                    "unknown",
                ),
                "z_hint_bp": _to_bp(entry.get("z_hint"), default_bp=5000),
                "bbox": [int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])],
                "source_roi": parent_roi.roi_id if parent_roi else "thumbnail",
            }
        )
    return out


def _parse_facts(raw: dict[str, Any], *, parent_roi: _Roi) -> list[dict[str, Any]]:
    entries = raw.get("facts", []) if isinstance(raw.get("facts"), list) else []
    out: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        key = _clean_text(entry.get("key"))
        value = _clean_text(entry.get("value"))
        if not key or not value:
            continue
        out.append(
            {
                "fact_id": f"{parent_roi.roi_id}:f:{idx}",
                "key": key,
                "value": value,
                "confidence_bp": _to_bp(entry.get("confidence"), default_bp=7000),
                "source_roi": parent_roi.roi_id,
            }
        )
    return out


def _adv_fact_topics(facts: list[dict[str, Any]]) -> set[str]:
    topics: set[str] = set()
    for item in facts:
        if not isinstance(item, dict):
            continue
        key = _clean_text(item.get("key")).casefold()
        if not key.startswith("adv."):
            continue
        match = re.match(r"^adv\.([a-z0-9_]+)\.", key)
        if not match:
            continue
        topics.add(str(match.group(1)))
    return topics


def _dedupe_elements(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[int, int, int, int], str]] = set()
    for item in items:
        bbox_raw = item.get("bbox")
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            continue
        try:
            bbox = (int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3]))
        except Exception:
            continue
        kind = _clean_text(item.get("type")) or "other"
        text = _clean_text(item.get("text"))
        fp = (kind, bbox, text)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(
            {
                "type": kind,
                "bbox": [bbox[0], bbox[1], bbox[2], bbox[3]],
                "text": text,
                "interactable": bool(item.get("interactable", False)),
                "state": item.get("state", {}) if isinstance(item.get("state"), dict) else {},
                "children": item.get("children", []) if isinstance(item.get("children"), list) else [],
            }
        )
    out.sort(key=lambda e: (int(e["bbox"][1]), int(e["bbox"][0]), str(e.get("type") or ""), str(e.get("text") or "")))
    return out[:1200]


def _dedupe_windows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        bbox_raw = item.get("bbox")
        if not isinstance(bbox_raw, list) or len(bbox_raw) != 4:
            continue
        try:
            bbox = (int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3]))
        except Exception:
            continue
        app = _clean_text(item.get("app"))
        duplicate = False
        for existing in out:
            eb = existing.get("bbox")
            if not isinstance(eb, list) or len(eb) != 4:
                continue
            ebt = (int(eb[0]), int(eb[1]), int(eb[2]), int(eb[3]))
            if _iou(bbox, ebt) >= 0.9 and app.casefold() == _clean_text(existing.get("app")).casefold():
                duplicate = True
                break
        if duplicate:
            continue
        out.append(
            {
                "window_id": str(item.get("window_id") or ""),
                "label": _clean_text(item.get("label")),
                "app": app,
                "context": _enum_or_default(item.get("context"), {"host", "vdi", "unknown"}, "unknown"),
                "visibility": _enum_or_default(
                    item.get("visibility"),
                    {"fully_visible", "partially_occluded", "unknown"},
                    "unknown",
                ),
                "z_hint_bp": int(item.get("z_hint_bp") or 5000),
                "bbox": [bbox[0], bbox[1], bbox[2], bbox[3]],
                "source_roi": _clean_text(item.get("source_roi")),
            }
        )
    out.sort(key=lambda w: (-int(w.get("z_hint_bp") or 0), str(w.get("app") or "")))
    return out[:160]


def _dedupe_facts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = _clean_text(item.get("key"))
        value = _clean_text(item.get("value"))
        if not key or not value:
            continue
        fp = (key.casefold(), value.casefold())
        if fp in seen:
            continue
        seen.add(fp)
        out.append(
            {
                "fact_id": _clean_text(item.get("fact_id")),
                "key": key,
                "value": value,
                "confidence_bp": int(item.get("confidence_bp") or 7000),
                "source_roi": _clean_text(item.get("source_roi")),
            }
        )
    out.sort(key=lambda f: (-int(f.get("confidence_bp") or 0), str(f.get("key") or ""), str(f.get("value") or "")))
    return out[:800]
