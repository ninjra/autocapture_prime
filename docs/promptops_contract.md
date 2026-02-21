# PromptOps Contract API

## Purpose
Provide one stable PromptOps interface for all query/model callsites so prompt preparation and outcome telemetry are consistent.

## API
Module: `autocapture/promptops/api.py`

- `PromptOpsAPI.prepare(task_class, raw_prompt, context)`
  - Returns: `PromptPrepared(prompt, prompt_id, applied, strategy, trace)`
  - Use for both query and non-query prompt preparation.

- `PromptOpsAPI.record_outcome(...)`
  - Persists `promptops.model_interaction` and optional review/update path.
  - Use after model/provider calls.

- `PromptOpsAPI.recommend_template(task_class, raw_prompt, context)`
  - Returns stored or generated candidate template recommendation.

## Service access
Module: `autocapture/promptops/service.py`

- `get_promptops_api(config)` returns a process-cached API instance.
- `get_promptops_layer(config)` remains available for internal compatibility.

## Current routed callsites
- `autocapture_nx/kernel/query.py`
  - state query prompt prepare + outcome
  - classic query prompt prepare + outcome
  - hard VLM topic prompt prepare + outcome
- `autocapture/gateway/router.py`
  - gateway chat prompt prepare
- `autocapture/memory/answer_orchestrator.py`
  - local LLM prompt prepare

## Invariants
- Localhost-only review endpoint policy remains enforced by gates.
- `promptops.require_query_path=true` fail-closes when query path preparation is unavailable.
- PromptOps optimizer runs only in idle windows (`promptops.optimize` runtime job).
- PromptOps examples are refreshed from query traces/metrics into `promptops.examples_path` (`data/promptops/examples.json` by default).
