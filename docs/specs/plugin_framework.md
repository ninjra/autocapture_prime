### 1) Plugin interface (Python)

Implement a minimal plugin framework with strict I/O typing, schema validation, and deterministic ordering.

```python
# src/core/plugin_base.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Protocol, Tuple, Optional

@dataclass(frozen=True)
class PluginMeta:
    id: str
    version: str

@dataclass(frozen=True)
class RunContext:
    run_id: str
    ts_ms: int
    config: Dict[str, Any]
    # handles injected by orchestrator:
    stores: Any
    logger: Any

@dataclass(frozen=True)
class PluginInput:
    # Named inputs, e.g. {"frame": Frame, "image": np.ndarray, "tokens": [...]}.
    items: Dict[str, Any]

@dataclass(frozen=True)
class PluginOutput:
    items: Dict[str, Any]       # artifacts + intermediate outputs
    metrics: Dict[str, float]   # numeric metrics only
    diagnostics: List[Dict[str, Any]]  # structured warnings/errors

class Plugin(Protocol):
    meta: PluginMeta
    requires: Tuple[str, ...]      # required input keys
    provides: Tuple[str, ...]      # output keys

    def run(self, inp: PluginInput, ctx: RunContext) -> PluginOutput: ...
```

### 2) Determinism rules (enforced by orchestrator)

* All plugin outputs must be **purely derived** from inputs + config.
* Any list output must be **sorted** deterministically (document sort keys).
* All hashes computed from **canonical JSON** (sorted keys, stable float quantization).
* If a plugin calls a model:

  * decode must be deterministic
  * output must be schema‑validated and normalized

### 3) Orchestrator contract

* Executes plugins in declared order.
* Validates `requires` present before running.
* If a plugin fails:

  * If `required=True` in pipeline config → mark run as incomplete; still persist diagnostics.
  * Otherwise continue.

### 4) Versioning

* Plugin versions are semantic: `MAJOR.MINOR.PATCH`.
* Schema changes require increment `schema_version`.

---
