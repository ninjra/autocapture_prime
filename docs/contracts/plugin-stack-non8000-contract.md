# Plugin Stack Contract: Processing-Only Non-8000 Default

## Purpose
Define the default plugin posture when Hypervisor owns capture and local `:8000` services are unavailable.

## Classification

### 1) `capture_deprecated` (must remain disabled)
- `builtin.capture.audio.windows`
- `builtin.capture.screenshot.windows`
- `builtin.capture.basic`
- `builtin.capture.windows`

### 2) `requires_8000` (must remain disabled in this profile)
- `builtin.processing.sst.ui_vlm`
- `builtin.vlm.vllm_localhost`
- `builtin.embedder.vllm_localhost`
- `builtin.answer.synth_vllm_localhost`

### 3) `required_non8000_enabled` (must be enabled by default)
- `builtin.processing.sst.pipeline`
- `builtin.processing.sst.uia_context`
- `builtin.runtime.governor`
- `builtin.runtime.scheduler`
- `builtin.sst.preprocess.normalize`
- `builtin.sst.preprocess.tile`
- `builtin.sst.ocr.onnx`
- `builtin.sst.ui.parse`
- `builtin.sst.layout.assemble`
- `builtin.sst.extract.table`
- `builtin.sst.extract.spreadsheet`
- `builtin.sst.extract.code`
- `builtin.sst.extract.chart`
- `builtin.sst.track.cursor`
- `builtin.sst.build.state`
- `builtin.sst.match.ids`
- `builtin.sst.temporal.segment`
- `builtin.sst.build.delta`
- `builtin.sst.infer.action`
- `builtin.sst.compliance.redact`
- `builtin.sst.persist`
- `builtin.sst.index`
- `builtin.sst.qa.answers`
- `builtin.state.vector.linear`
- `builtin.state.workflow.miner`
- `builtin.state.anomaly`
- `builtin.state.jepa.training`

## Runtime Flags
- `processing.idle.extractors.vlm=false`
- `processing.sst.ui_vlm.enabled=false`

## Enforcement
- Gate: `tools/gate_config_matrix.py`
- Doctor check: `capture_plugins_deprecated` in `autocapture_nx/kernel/loader.py`
- Output artifact: `artifacts/config/gate_config_matrix.json`
