from pathlib import Path


def test_agent_queue_blocks_delete_commands():
    script = Path("ops/dev/agent_queue.ps1").read_text(encoding="utf-8")
    assert "Test-DeleteCommand" in script
    assert "remove-item" in script.lower()
    assert "rm" in script.lower()
    assert "rmdir" in script.lower()


def test_agent_queue_prompts_by_default():
    script = Path("ops/dev/agent_queue.ps1").read_text(encoding="utf-8")
    assert "Read-Host" in script
