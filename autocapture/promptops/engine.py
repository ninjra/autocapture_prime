"""PromptOps optimization layer for prompt handling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from autocapture.core.hashing import hash_text
from autocapture.plugins.manager import PluginManager
from autocapture.promptops.evaluate import evaluate_prompt
from autocapture.promptops.github import create_pull_request
from autocapture.promptops.propose import propose_prompt
from autocapture.promptops.sources import PromptBundle, snapshot_sources
from autocapture.promptops.validate import DEFAULT_BANNED, validate_prompt


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)


def _data_root(config: dict[str, Any]) -> Path:
    paths = config.get("paths", {}) if isinstance(config, dict) else {}
    data_dir = paths.get("data_dir") or config.get("storage", {}).get("data_dir", "data")
    return Path(data_dir)


@dataclass
class PromptOpsResult:
    prompt_id: str
    prompt: str
    applied: bool
    mode: str
    proposal: dict[str, Any] | None
    validation: dict[str, Any] | None
    evaluation: dict[str, Any] | None
    sources: list[dict[str, Any]]


class PromptStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, str] = {}

    def _path(self, prompt_id: str) -> Path:
        return self.root / f"{_safe_name(prompt_id)}.txt"

    def get(self, prompt_id: str) -> str | None:
        if prompt_id in self._cache:
            return self._cache[prompt_id]
        path = self._path(prompt_id)
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        self._cache[prompt_id] = text
        return text

    def set(self, prompt_id: str, text: str) -> Path:
        path = self._path(prompt_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self._cache[prompt_id] = text
        return path


class PromptHistory:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def record(self, prompt_id: str, payload: dict[str, Any]) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = f"{_safe_name(prompt_id)}_{stamp}.json"
        path = self.root / name
        path.write_text(_safe_json(payload), encoding="utf-8")
        return path


def _safe_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True)


class PromptOpsLayer:
    """Applies PromptOps validation + proposals to prompts."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._bundle_instance: PromptBundle | None = None
        self._store = PromptStore(self._prompt_dir())
        self._history = PromptHistory(self._history_dir())

    def _prompt_cfg(self) -> dict[str, Any]:
        return self._config.get("promptops", {}) if isinstance(self._config, dict) else {}

    def _prompt_dir(self) -> Path:
        cfg = self._prompt_cfg()
        root = _data_root(self._config)
        return Path(cfg.get("prompt_dir") or root / "promptops" / "prompts")

    def _history_dir(self) -> Path:
        cfg = self._prompt_cfg()
        root = _data_root(self._config)
        return Path(cfg.get("history_dir") or root / "promptops" / "history")

    def _bundle_name(self) -> str:
        cfg = self._prompt_cfg()
        return str(cfg.get("bundle_name", "default"))

    def _load_bundle(self) -> PromptBundle | None:
        if self._bundle_instance is not None:
            return self._bundle_instance
        try:
            manager = PluginManager(self._config, safe_mode=bool(self._config.get("plugins", {}).get("safe_mode", False)))
            ext = manager.get_extension("prompt.bundle", name=self._bundle_name())
            self._bundle_instance = ext.instance
        except Exception:
            self._bundle_instance = None
        return self._bundle_instance

    def _snapshot(self, sources: Iterable[Any]) -> dict[str, Any]:
        bundle = self._load_bundle()
        if bundle is not None:
            return bundle.snapshot(sources)
        return snapshot_sources(sources)

    def _examples_for(self, prompt_id: str) -> list[dict[str, Any]]:
        cfg = self._prompt_cfg()
        examples = cfg.get("examples", {})
        if isinstance(examples, dict):
            return list(examples.get(prompt_id, []))
        if isinstance(examples, list):
            return list(examples)
        return []

    def prepare_prompt(
        self,
        prompt: str,
        *,
        prompt_id: str = "default",
        sources: Iterable[Any] | None = None,
        examples: list[dict[str, Any]] | None = None,
        persist: bool | None = None,
        strategy: str | None = None,
    ) -> PromptOpsResult:
        cfg = self._prompt_cfg()
        enabled = bool(cfg.get("enabled", True))
        mode = str(cfg.get("mode", "auto_apply"))
        if not enabled or mode == "off":
            return PromptOpsResult(
                prompt_id=prompt_id,
                prompt=prompt,
                applied=False,
                mode=mode,
                proposal=None,
                validation=None,
                evaluation=None,
                sources=[],
            )

        sources = list(cfg.get("sources", []) if sources is None else sources)
        snapshot = self._snapshot(sources)
        snapshot_sources_list = list(snapshot.get("sources", []))
        if strategy is None:
            strategy = str(cfg.get("strategy", "append_sources"))
        if strategy == "append_sources" and not snapshot_sources_list:
            strategy = "none"

        current_prompt = self._store.get(prompt_id) or prompt
        proposal = propose_prompt(current_prompt, snapshot, strategy=strategy)
        candidate = proposal.get("proposal", current_prompt)

        validation = validate_prompt(
            candidate,
            max_chars=int(cfg.get("max_chars", 8000)),
            max_tokens=int(cfg.get("max_tokens", 2000)),
            banned_patterns=cfg.get("banned_patterns", DEFAULT_BANNED),
        )
        min_pass_rate = cfg.get("min_pass_rate")
        if min_pass_rate is None:
            pct = int(cfg.get("min_pass_rate_pct", 100))
            min_pass_rate = max(0.0, min(1.0, pct / 100.0))
        eval_examples = examples if examples is not None else self._examples_for(prompt_id)
        evaluation = evaluate_prompt(
            candidate,
            eval_examples,
            min_pass_rate=float(min_pass_rate),
            require_citations=bool(cfg.get("require_citations", True)),
        )
        ok = bool(validation.get("ok")) and bool(evaluation.get("ok"))

        persist_default = bool(cfg.get("persist_prompts", False))
        persist = persist_default if persist is None else bool(persist)
        applied = False
        selected_prompt = current_prompt
        if ok and mode in ("auto_apply", "apply"):
            selected_prompt = candidate
            applied = True
            if persist:
                self._store.set(prompt_id, candidate)

        history_cfg = cfg.get("history", {})
        if history_cfg.get("enabled", True):
            history_payload = {
                "prompt_id": prompt_id,
                "mode": mode,
                "applied": applied,
                "proposal_id": proposal.get("proposal_id"),
                "proposal_hash": hash_text(str(proposal.get("proposal", ""))),
                "validation": validation,
                "evaluation": evaluation,
                "sources": snapshot_sources_list,
            }
            if history_cfg.get("include_prompt", False):
                history_payload["prompt"] = selected_prompt
            self._history.record(prompt_id, history_payload)

        github_cfg = cfg.get("github", {})
        if bool(github_cfg.get("enabled", False)) and proposal.get("diff"):
            create_pull_request(
                title=str(github_cfg.get("title", "PromptOps update")),
                body=str(github_cfg.get("body", "Automated prompt update.")),
                diff=str(proposal.get("diff")),
                enabled=True,
                output_path=str(github_cfg.get("output_path", "artifacts/promptops_pr.json")),
            )

        return PromptOpsResult(
            prompt_id=prompt_id,
            prompt=selected_prompt,
            applied=applied,
            mode=mode,
            proposal=proposal,
            validation=validation,
            evaluation=evaluation,
            sources=snapshot_sources_list,
        )

    def prepare_query(
        self,
        query: str,
        *,
        prompt_id: str = "query.default",
        sources: Iterable[Any] | None = None,
    ) -> PromptOpsResult:
        cfg = self._prompt_cfg()
        strategy = str(cfg.get("query_strategy", "none"))
        return self.prepare_prompt(
            query,
            prompt_id=prompt_id,
            sources=sources,
            persist=False,
            strategy=strategy,
        )
