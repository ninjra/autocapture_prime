from tools.validate_model_manifest import validate_manifest


def test_model_manifest_validation_passes():
    payload = {
        "schema_version": 1,
        "root_dir": "D:\\autocapture\\models",
        "huggingface": {
            "models": [
                {
                    "id": "deepseek-ai/DeepSeek-OCR-2",
                    "kind": "vlm",
                    "required": True,
                    "provider_id": "builtin.vlm.deepseek_ocr2",
                    "subdir": "deepseek-ocr2",
                },
                {
                    "id": "Ooredoo-Group/rapidocr-models",
                    "kind": "ocr",
                    "required": True,
                    "provider_id": "builtin.ocr.rapid",
                    "subdir": "rapidocr-models",
                    "files": {
                        "det": "det.onnx",
                        "rec": "rec.onnx",
                        "cls": "cls.onnx",
                    },
                },
            ]
        },
        "vllm": {
            "server": {
                "host": "127.0.0.1",
                "port": 8000,
                "api_key": "",
            },
            "models": [
                {"id": "Qwen/Qwen2.5-7B-Instruct", "kind": "llm", "required": False},
            ],
        },
    }
    errors = validate_manifest(payload)
    assert errors == []


def test_model_manifest_validation_duplicate_provider():
    payload = {
        "schema_version": 1,
        "root_dir": "D:\\autocapture\\models",
        "huggingface": {
            "models": [
                {
                    "id": "model/a",
                    "kind": "vlm",
                    "provider_id": "builtin.vlm.shared",
                    "subdir": "a",
                },
                {
                    "id": "model/b",
                    "kind": "vlm",
                    "provider_id": "builtin.vlm.shared",
                    "subdir": "b",
                },
            ]
        },
    }
    errors = validate_manifest(payload)
    assert any("duplicate provider_id" in err for err in errors)


def test_model_manifest_validation_vllm_host_must_be_localhost():
    payload = {
        "schema_version": 1,
        "root_dir": "D:\\autocapture\\models",
        "huggingface": {"models": []},
        "vllm": {
            "server": {"host": "0.0.0.0", "port": 8000, "api_key": ""},
            "models": [{"id": "Qwen/Qwen2.5-7B-Instruct", "kind": "llm"}],
        },
    }
    errors = validate_manifest(payload)
    assert any("vllm.server.host must be 127.0.0.1" in err for err in errors)
