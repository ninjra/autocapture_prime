"""Deterministic RNG services and strict guardrails."""

from __future__ import annotations

import hashlib
import random
import threading
from dataclasses import dataclass
from typing import Any


_rng_local = threading.local()
_guard_lock = threading.Lock()
_guard_installed = False
_orig_inst = getattr(random, "_inst", None)
_orig_random_cls = random.Random
_orig_system_random_cls = random.SystemRandom


def _hash_seed(*parts: str) -> int:
    payload = "|".join(parts).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


@dataclass(frozen=True)
class RNGSeed:
    run_seed: int
    plugin_seed: int
    seed_hex: str


class RNGService:
    def __init__(
        self,
        *,
        enabled: bool,
        strict: bool,
        base_seed: str,
        run_id: str,
        use_run_id: bool,
    ) -> None:
        self.enabled = bool(enabled)
        self.strict = bool(strict)
        seed_parts = [base_seed]
        if use_run_id:
            seed_parts.append(run_id or "run")
        self._run_seed = _hash_seed(*seed_parts)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "RNGService":
        kernel_cfg = config.get("kernel", {}) if isinstance(config, dict) else {}
        rng_cfg = kernel_cfg.get("rng", {}) if isinstance(kernel_cfg, dict) else {}
        enabled = bool(rng_cfg.get("enabled", True))
        strict = bool(rng_cfg.get("strict", True))
        base_seed = str(rng_cfg.get("seed") or "autocapture-nx")
        use_run_id = bool(rng_cfg.get("use_run_id", True))
        run_id = ""
        if isinstance(config, dict):
            run_id = str(config.get("runtime", {}).get("run_id") or "")
        return cls(
            enabled=enabled,
            strict=strict,
            base_seed=base_seed,
            run_id=run_id,
            use_run_id=use_run_id,
        )

    def seed_for_plugin(self, plugin_id: str) -> RNGSeed:
        plugin_seed = _hash_seed(str(self._run_seed), plugin_id)
        seed_hex = f"{plugin_seed:016x}"
        return RNGSeed(run_seed=self._run_seed, plugin_seed=plugin_seed, seed_hex=seed_hex)

    def rng_for_plugin(self, plugin_id: str) -> random.Random:
        seed = self.seed_for_plugin(plugin_id).plugin_seed
        return _orig_random_cls(seed)


class _ThreadRNGProxy:
    def __getattr__(self, name: str):
        rng = getattr(_rng_local, "rng", None)
        strict = bool(getattr(_rng_local, "strict", False))
        target = rng if rng is not None else _orig_inst
        attr = getattr(target, name)
        if rng is None and strict:
            if callable(attr):
                def _blocked(*_args, **_kwargs):
                    raise RuntimeError("Unseeded random usage")

                return _blocked
            raise RuntimeError("Unseeded random usage")
        return attr


def install_rng_guard() -> None:
    global _guard_installed
    if _guard_installed:
        return
    with _guard_lock:
        if _guard_installed:
            return
        if _orig_inst is not None:
            setattr(random, "_inst", _ThreadRNGProxy())
            _rebind_module_functions()

        class _GuardedRandom(_orig_random_cls):  # type: ignore[misc]
            def __init__(self, seed: int | None = None) -> None:
                if seed is None:
                    seed = getattr(_rng_local, "seed", None)
                    if seed is None and bool(getattr(_rng_local, "strict", False)):
                        raise RuntimeError("Unseeded random.Random()")
                super().__init__(seed)

        class _GuardedSystemRandom(_orig_system_random_cls):  # type: ignore[misc]
            def __init__(self, *args, **kwargs) -> None:
                if bool(getattr(_rng_local, "strict", False)):
                    raise RuntimeError("SystemRandom not allowed in strict RNG mode")
                super().__init__(*args, **kwargs)

        setattr(random, "Random", _GuardedRandom)
        setattr(random, "SystemRandom", _GuardedSystemRandom)
        _guard_installed = True


def _rebind_module_functions() -> None:
    def _bind(name: str):
        def _call(*args, **kwargs):
            target = getattr(random._inst, name)
            return target(*args, **kwargs)

        return _call

    for name in (
        "seed",
        "random",
        "randrange",
        "randint",
        "choice",
        "choices",
        "shuffle",
        "sample",
        "uniform",
        "triangular",
        "betavariate",
        "expovariate",
        "gammavariate",
        "gauss",
        "lognormvariate",
        "normalvariate",
        "paretovariate",
        "vonmisesvariate",
        "weibullvariate",
        "getstate",
        "setstate",
        "getrandbits",
    ):
        if hasattr(random, name):
            setattr(random, name, _bind(name))


def set_thread_seed(seed: int, *, strict: bool) -> None:
    install_rng_guard()
    _rng_local.rng = _orig_random_cls(seed)
    _rng_local.seed = seed
    _rng_local.strict = bool(strict)


class RNGScope:
    def __init__(self, seed: int | None, *, strict: bool, enabled: bool) -> None:
        self._seed = seed
        self._strict = bool(strict)
        self._enabled = bool(enabled)
        self._prev_rng = None
        self._prev_seed = None
        self._prev_strict = None

    def __enter__(self) -> None:
        if not self._enabled or self._seed is None:
            return None
        install_rng_guard()
        self._prev_rng = getattr(_rng_local, "rng", None)
        self._prev_seed = getattr(_rng_local, "seed", None)
        self._prev_strict = getattr(_rng_local, "strict", None)
        _rng_local.rng = _orig_random_cls(self._seed)
        _rng_local.seed = self._seed
        _rng_local.strict = self._strict
        return None

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._enabled or self._seed is None:
            return None
        if self._prev_rng is None:
            if hasattr(_rng_local, "rng"):
                delattr(_rng_local, "rng")
        else:
            _rng_local.rng = self._prev_rng
        if self._prev_seed is None:
            if hasattr(_rng_local, "seed"):
                delattr(_rng_local, "seed")
        else:
            _rng_local.seed = self._prev_seed
        if self._prev_strict is None:
            if hasattr(_rng_local, "strict"):
                delattr(_rng_local, "strict")
        else:
            _rng_local.strict = self._prev_strict
        return None
