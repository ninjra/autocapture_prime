from __future__ import annotations

import json
from pathlib import Path

from tools import import_gemini_cli_prompt_library as mod


def _seed_repo(root: Path) -> None:
    (root / "commands" / "debugging").mkdir(parents=True, exist_ok=True)
    (root / "commands" / "testing").mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(
        "\n".join(
            [
                "# Prompt Library",
                "",
                "## 📚 Prompt Engineering Tips",
                "### 1. **Be Specific**",
                "### 2. **Provide Structure**",
                "### 3. **Include Context**",
                "",
                "## Other Section",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "commands" / "debugging" / "debug-error.toml").write_text(
        'prompt = """\n# Debug Error\nFind root cause and fix.\n"""\n',
        encoding="utf-8",
    )
    (root / "commands" / "testing" / "generate-unit-tests.toml").write_text(
        'prompt = """\n# Generate Unit Tests\nWrite deterministic tests.\n"""\n',
        encoding="utf-8",
    )


def test_build_payload_extracts_prompts_and_principles(tmp_path: Path) -> None:
    repo = tmp_path / "gemini"
    _seed_repo(repo)
    payload = mod.build_payload(repo)
    assert int(payload.get("prompt_count", 0) or 0) == 2
    assert payload.get("principles") == ["Be Specific", "Provide Structure", "Include Context"]
    commands = payload.get("commands", [])
    assert isinstance(commands, list) and len(commands) == 2
    assert str(commands[0].get("id") or "") == "debugging.debug-error"
    assert str(commands[1].get("id") or "") == "testing.generate-unit-tests"
    assert str(commands[0].get("command") or "") == "/debugging:debug-error"
    assert str(commands[0].get("prompt_text") or "").startswith("# Debug Error")
    assert str(payload.get("content_hash") or "").strip()


def test_render_runtime_source_contains_catalog_rows(tmp_path: Path) -> None:
    repo = tmp_path / "gemini"
    _seed_repo(repo)
    payload = mod.build_payload(repo)
    text = mod.render_runtime_source(payload)
    assert "PromptOps Idea Pack: Gemini CLI Prompt Library" in text
    assert "/debugging:debug-error" in text
    assert "Prompt Engineering Principles" in text
    assert "intent:" in text


def test_tool_main_writes_catalog_and_runtime_files(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "gemini"
    _seed_repo(repo)
    catalog = tmp_path / "out" / "catalog.json"
    runtime = tmp_path / "out" / "ideas.md"
    monkeypatch.setattr(
        "sys.argv",
        [
            "import_gemini_cli_prompt_library.py",
            "--repo",
            str(repo),
            "--catalog-out",
            str(catalog),
            "--runtime-out",
            str(runtime),
        ],
    )
    rc = mod.main()
    assert rc == 0
    assert catalog.exists()
    assert runtime.exists()
    payload = json.loads(catalog.read_text(encoding="utf-8"))
    assert int(payload.get("prompt_count", 0) or 0) == 2
