"""Temporal segmentation based on phash and cheap visual diffs."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .utils import hamming_distance


@dataclass(frozen=True)
class SegmentDecision:
    boundary: bool
    reason: str
    phash_distance: int
    diff_score_bp: int


def decide_boundary(
    *,
    phash: str,
    prev_phash: str | None,
    image_rgb: Image.Image,
    prev_downscaled: tuple[int, ...] | None,
    d_stable: int,
    d_boundary: int,
    diff_threshold_bp: int,
    downscale_px: int,
) -> tuple[SegmentDecision, tuple[int, ...]]:
    downscaled = _downscale_gray(image_rgb, downscale_px)
    if not prev_phash:
        return SegmentDecision(True, "first_frame", len(phash), 10000), downscaled
    dist = hamming_distance(phash, prev_phash)
    if dist <= d_stable:
        return SegmentDecision(False, "stable_phash", dist, 0), downscaled
    if dist >= d_boundary:
        return SegmentDecision(True, "phash_boundary", dist, 10000), downscaled
    diff_bp = _diff_score_bp(downscaled, prev_downscaled)
    if diff_bp >= diff_threshold_bp:
        return SegmentDecision(True, "diff_boundary", dist, diff_bp), downscaled
    return SegmentDecision(False, "diff_stable", dist, diff_bp), downscaled


def _downscale_gray(image_rgb: Image.Image, downscale_px: int) -> tuple[int, ...]:
    small = image_rgb.convert("L").resize((downscale_px, downscale_px), Image.BILINEAR)
    return tuple(int(v) for v in small.tobytes())


def _diff_score_bp(current: tuple[int, ...], prev: tuple[int, ...] | None) -> int:
    if not prev or len(prev) != len(current):
        return 10000
    total = 0
    for a, b in zip(current, prev):
        total += abs(int(a) - int(b))
    max_total = 255 * max(1, len(current))
    # Convert to basis points in [0, 10000].
    return int((total * 10000) // max_total)
