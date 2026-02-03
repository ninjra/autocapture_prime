from autocapture_nx.kernel.derived_records import build_text_record


def test_build_text_record_uses_provider_override():
    config = {
        "models": {
            "providers": {
                "builtin.vlm.deepseek_ocr2": {
                    "model_id": "deepseek-ai/DeepSeek-OCR-2",
                    "model_path": "D:\\autocapture\\models\\deepseek-ocr2",
                    "revision": "test-rev",
                    "files": {"weights": "model.safetensors"},
                }
            }
        }
    }
    record = {
        "record_type": "evidence.capture.frame",
        "run_id": "run_1",
        "ts_utc": "2026-02-03T00:00:00Z",
    }
    payload = build_text_record(
        kind="vlm",
        text="hello world",
        source_id="run_1/evidence.capture.frame/0",
        source_record=record,
        provider_id="builtin.vlm.deepseek_ocr2",
        config=config,
        ts_utc="2026-02-03T00:00:00Z",
    )
    assert payload is not None
    assert payload["model_id"] == "deepseek-ai/DeepSeek-OCR-2"
    assert payload.get("model_revision") == "test-rev"
    assert payload.get("model_path") == "D:\\autocapture\\models\\deepseek-ocr2"
    assert payload.get("model_files") == {"weights": "model.safetensors"}
