"""JEPA model helpers (training, serialization, inference)."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class JEPAModel:
    model_version: str
    training_run_id: str
    input_dim: int
    latent_dim: int
    encoder: list[list[float]]
    predictor: list[list[float]]
    projection_seed: str
    weight_scale: int
    config_hash: str
    dataset_hash: str
    created_ts_ms: int
    eval: dict[str, Any]
    activation: str = "tanh"

    def encode(self, features: list[float]) -> list[float]:
        vec = _normalize(_ensure_dim(features, self.input_dim))
        latent = _matvec(self.encoder, vec)
        latent = _activate(latent, self.activation)
        return _normalize(latent)

    def predict(self, latent: list[float]) -> list[float]:
        vec = _ensure_dim(latent, self.latent_dim)
        pred = _matvec(self.predictor, vec)
        pred = _activate(pred, self.activation)
        return _normalize(pred)

    def embed(self, features: list[float], *, out_dim: int = 768) -> list[float]:
        latent = self.encode(features)
        projected = _project_vector(latent, out_dim=out_dim, seed=self.projection_seed)
        return _normalize(projected)

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "model_version": self.model_version,
            "training_run_id": self.training_run_id,
            "input_dim": int(self.input_dim),
            "latent_dim": int(self.latent_dim),
            "weight_scale": int(self.weight_scale),
            "activation": str(self.activation or "tanh"),
            "projection_seed": str(self.projection_seed),
            "config_hash": str(self.config_hash),
            "dataset_hash": str(self.dataset_hash),
            "created_ts_ms": int(self.created_ts_ms),
            "eval": self.eval if isinstance(self.eval, dict) else {},
            "encoder": _quantize_matrix(self.encoder, self.weight_scale),
            "predictor": _quantize_matrix(self.predictor, self.weight_scale),
        }

    @staticmethod
    def from_payload(payload: dict[str, Any]) -> "JEPAModel":
        weight_scale = int(payload.get("weight_scale", 1) or 1)
        encoder = _dequantize_matrix(payload.get("encoder", []), weight_scale)
        predictor = _dequantize_matrix(payload.get("predictor", []), weight_scale)
        return JEPAModel(
            model_version=str(payload.get("model_version") or ""),
            training_run_id=str(payload.get("training_run_id") or ""),
            input_dim=int(payload.get("input_dim", 0) or 0),
            latent_dim=int(payload.get("latent_dim", 0) or 0),
            encoder=encoder,
            predictor=predictor,
            projection_seed=str(payload.get("projection_seed") or ""),
            weight_scale=weight_scale,
            config_hash=str(payload.get("config_hash") or ""),
            dataset_hash=str(payload.get("dataset_hash") or ""),
            created_ts_ms=int(payload.get("created_ts_ms", 0) or 0),
            eval=payload.get("eval", {}) if isinstance(payload.get("eval"), dict) else {},
            activation=str(payload.get("activation") or "tanh"),
        )


def train_model(
    features: list[list[float]],
    *,
    model_version: str,
    training_run_id: str,
    config_hash: str,
    dataset_hash: str,
    training_cfg: dict[str, Any],
    eval_summary: dict[str, Any],
    created_ts_ms: int,
) -> tuple[JEPAModel, dict[str, Any]]:
    if not features or len(features) < 2:
        raise ValueError("training_requires_sequence")
    input_dim = len(features[0])
    latent_dim = int(training_cfg.get("latent_dim", 64) or 64)
    latent_dim = max(8, min(latent_dim, input_dim))
    epochs = int(training_cfg.get("epochs", 3) or 3)
    epochs = max(1, min(epochs, 10))
    learning_rate = float(training_cfg.get("learning_rate", 0.01) or 0.01)
    max_samples = int(training_cfg.get("max_samples", 200) or 200)
    init_scale = float(training_cfg.get("init_scale", 0.02) or 0.02)
    weight_scale = int(training_cfg.get("weight_scale", 1000000) or 1000000)
    seed = str(training_cfg.get("seed") or config_hash or "seed")
    projection_seed = str(training_cfg.get("projection_seed") or model_version or config_hash or "projection")
    activation = str(training_cfg.get("activation") or "tanh")

    ordered = list(features)
    if len(ordered) > max_samples:
        step = max(1, len(ordered) // max_samples)
        ordered = ordered[::step][:max_samples]
    ordered = [_ensure_dim(_normalize(vec), input_dim) for vec in ordered]

    encoder = _init_matrix(latent_dim, input_dim, seed=f"{seed}:enc", scale=init_scale)
    predictor = _init_matrix(latent_dim, latent_dim, seed=f"{seed}:pred", scale=init_scale)
    clip = float(training_cfg.get("error_clip", 1.0) or 1.0)

    loss_values: list[float] = []
    total_steps = 0

    for _epoch in range(epochs):
        epoch_loss = 0.0
        epoch_steps = 0
        for idx in range(len(ordered) - 1):
            f_t = ordered[idx]
            f_tp1 = ordered[idx + 1]
            h_t_pre = _matvec(encoder, f_t)
            h_tp1_pre = _matvec(encoder, f_tp1)
            h_t = _activate(h_t_pre, activation)
            h_tp1 = _activate(h_tp1_pre, activation)
            pred_pre = _matvec(predictor, h_t)
            pred = _activate(pred_pre, activation)
            error = [pred[i] - h_tp1[i] for i in range(latent_dim)]
            step_loss = sum(e * e for e in error) / float(latent_dim or 1)
            epoch_loss += step_loss
            epoch_steps += 1
            total_steps += 1
            if clip > 0:
                error = [max(-clip, min(clip, e)) for e in error]
            act_pred_grad = _activate_grad(pred_pre, activation)
            grad_pred = [2.0 * error[i] * act_pred_grad[i] for i in range(latent_dim)]
            back = _matvec_transpose(predictor, grad_pred)
            for i in range(latent_dim):
                err = grad_pred[i]
                row = predictor[i]
                for j in range(latent_dim):
                    row[j] -= learning_rate * err * h_t[j]
            act_h_t_grad = _activate_grad(h_t_pre, activation)
            act_h_tp1_grad = _activate_grad(h_tp1_pre, activation)
            for i in range(latent_dim):
                grad_from_pred = back[i] * act_h_t_grad[i]
                grad_from_tp1 = -2.0 * error[i] * act_h_tp1_grad[i]
                row = encoder[i]
                for j in range(input_dim):
                    row[j] -= learning_rate * (grad_from_pred * f_t[j] + grad_from_tp1 * f_tp1[j])
        if epoch_steps:
            loss_values.append(epoch_loss / float(epoch_steps))
        else:
            loss_values.append(0.0)

    model = JEPAModel(
        model_version=model_version,
        training_run_id=training_run_id,
        input_dim=input_dim,
        latent_dim=latent_dim,
        encoder=encoder,
        predictor=predictor,
        projection_seed=projection_seed,
        weight_scale=weight_scale,
        config_hash=config_hash,
        dataset_hash=dataset_hash,
        created_ts_ms=created_ts_ms,
        eval=eval_summary,
        activation=activation,
    )
    loss_history = [_format_float(val) for val in loss_values]
    report = {
        "schema_version": 1,
        "model_version": model_version,
        "training_run_id": training_run_id,
        "config_hash": config_hash,
        "dataset_hash": dataset_hash,
        "created_ts_ms": int(created_ts_ms),
        "input_dim": int(input_dim),
        "latent_dim": int(latent_dim),
        "samples_used": int(len(ordered)),
        "epochs": int(epochs),
        "steps": int(total_steps),
        "learning_rate": _format_float(learning_rate),
        "activation": activation,
        "loss_history": loss_history,
        "loss_final": _format_float(loss_values[-1]) if loss_values else "0",
        "loss_min": _format_float(min(loss_values)) if loss_values else "0",
        "loss_max": _format_float(max(loss_values)) if loss_values else "0",
        "eval": eval_summary if isinstance(eval_summary, dict) else {},
    }
    return model, _sanitize_report(report)


def _format_float(val: float) -> str:
    text = f"{val:.6f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _sanitize_report(payload: Any) -> Any:
    if isinstance(payload, bool):
        return payload
    if isinstance(payload, int):
        return payload
    if isinstance(payload, float):
        return _format_float(payload)
    if payload is None or isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return {str(k): _sanitize_report(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_sanitize_report(v) for v in payload]
    return str(payload)


def _ensure_dim(vec: list[float], dim: int) -> list[float]:
    if dim <= 0:
        return []
    if len(vec) == dim:
        return list(vec)
    if len(vec) > dim:
        return list(vec[:dim])
    out = list(vec)
    out.extend([0.0] * (dim - len(out)))
    return out


def _matvec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    if not matrix or not vector:
        return []
    out: list[float] = []
    for row in matrix:
        acc = 0.0
        for w, v in zip(row, vector):
            acc += w * v
        out.append(acc)
    return out


def _matvec_transpose(matrix: list[list[float]], vector: list[float]) -> list[float]:
    if not matrix or not vector:
        return []
    cols = len(matrix[0]) if matrix else 0
    out = [0.0] * cols
    for i, row in enumerate(matrix):
        if i >= len(vector):
            break
        val = vector[i]
        for j in range(min(cols, len(row))):
            out[j] += row[j] * val
    return out


def _normalize(vec: list[float]) -> list[float]:
    if not vec:
        return []
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _activate(vec: list[float], activation: str) -> list[float]:
    if activation == "tanh":
        return [math.tanh(v) for v in vec]
    if activation == "relu":
        return [v if v > 0.0 else 0.0 for v in vec]
    return list(vec)


def _activate_grad(vec: list[float], activation: str) -> list[float]:
    if activation == "tanh":
        return [1.0 - math.tanh(v) ** 2 for v in vec]
    if activation == "relu":
        return [1.0 if v > 0.0 else 0.0 for v in vec]
    return [1.0 for _v in vec]


def _init_matrix(rows: int, cols: int, *, seed: str, scale: float) -> list[list[float]]:
    rows = max(1, rows)
    cols = max(1, cols)
    seed_bytes = hashlib.sha256(seed.encode("utf-8")).digest()
    matrix: list[list[float]] = []
    for i in range(rows):
        row: list[float] = []
        for j in range(cols):
            h = hashlib.sha256(seed_bytes + i.to_bytes(2, "big") + j.to_bytes(2, "big")).digest()
            val = int.from_bytes(h[:2], "big") / 65535.0
            row.append((val * 2.0 - 1.0) * scale)
        matrix.append(row)
    return matrix


def _quantize_matrix(matrix: list[list[float]], scale: int) -> list[list[int]]:
    if not matrix:
        return []
    if scale <= 0:
        scale = 1
    quantized: list[list[int]] = []
    for row in matrix:
        quantized.append([int(round(val * scale)) for val in row])
    return quantized


def _dequantize_matrix(matrix: Iterable[Iterable[Any]], scale: int) -> list[list[float]]:
    if scale <= 0:
        scale = 1
    rows: list[list[float]] = []
    for row in matrix:
        if not isinstance(row, Iterable):
            continue
        rows.append([float(val) / scale for val in row])
    return rows


def _project_vector(vec: list[float], *, out_dim: int, seed: str) -> list[float]:
    if not vec:
        return [0.0] * out_dim
    in_dim = len(vec)
    scale = 1.0 / math.sqrt(float(in_dim) or 1.0)
    seed_bytes = hashlib.sha256(seed.encode("utf-8")).digest()
    out: list[float] = []
    for i in range(out_dim):
        acc = 0.0
        for j in range(in_dim):
            h = hashlib.sha256(seed_bytes + i.to_bytes(2, "big") + j.to_bytes(2, "big")).digest()
            weight = 1.0 if (h[0] & 1) == 1 else -1.0
            acc += weight * vec[j]
        out.append(acc * scale)
    return out
