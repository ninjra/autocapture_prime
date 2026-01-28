"""Image normalization, perceptual hashing, and tiling."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage
else:
    PILImage = Any

from .utils import clamp_bbox, sha256_bytes

BBox = tuple[int, int, int, int]


@dataclass(frozen=True)
class NormalizedImage:
    image_rgb: PILImage
    width: int
    height: int
    image_sha256: str
    phash: str


def normalize_image(
    image_bytes: bytes,
    *,
    strip_alpha: bool = True,
    phash_size: int = 8,
    phash_downscale: int = 32,
) -> NormalizedImage:
    if not image_bytes:
        raise RuntimeError("Missing image bytes")
    try:
        Image = _pil()
        img = Image.open(BytesIO(image_bytes))
        img.load()
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"Unable to decode image bytes: {exc}") from exc
    if strip_alpha and img.mode in {"RGBA", "LA"}:
        base = Image.new("RGB", img.size, (255, 255, 255))
        base.paste(img, mask=img.split()[-1])
        img = base
    if img.mode != "RGB":
        img = img.convert("RGB")
    width, height = img.size
    image_hash = sha256_bytes(image_bytes)
    phash = perceptual_hash(img, size=phash_size, downscale=phash_downscale)
    if width <= 0 or height <= 0:
        raise RuntimeError("Invalid image dimensions")
    if len(phash) != 64:
        raise RuntimeError("Invalid phash length")
    return NormalizedImage(img, width, height, image_hash, phash)


def perceptual_hash(image_rgb: PILImage, *, size: int = 8, downscale: int = 32) -> str:
    # Grayscale downscale for stable low-frequency features.
    Image = _pil()
    small = image_rgb.convert("L").resize((downscale, downscale), Image.LANCZOS)
    pixels = list(small.tobytes())
    mat = [pixels[i * downscale : (i + 1) * downscale] for i in range(downscale)]
    dct = _dct_2d(mat)
    coeffs: list[float] = []
    for y in range(size):
        for x in range(size):
            if x == 0 and y == 0:
                continue
            coeffs.append(dct[y][x])
    median = _median(coeffs) if coeffs else 0.0
    bits: list[str] = []
    for y in range(size):
        for x in range(size):
            if x == 0 and y == 0:
                bits.append("0")
                continue
            bits.append("1" if dct[y][x] >= median else "0")
    return "".join(bits)


def tile_image(
    image_rgb: PILImage,
    *,
    tile_max_px: int,
    overlap_px: int,
    add_full_frame: bool,
    focus_tokens: list[dict[str, Any]] | None = None,
    focus_conf_bp: int = 0,
    focus_padding_px: int = 24,
    focus_max_patches: int = 0,
    focus_cluster_gap_px: int = 48,
) -> list[dict[str, Any]]:
    width, height = image_rgb.size
    tiles: list[dict[str, Any]] = []
    if add_full_frame:
        tiles.append(_make_patch("full_frame", (0, 0, width, height), image_rgb))

    step = max(1, tile_max_px - overlap_px)
    x_starts = _starts(width, tile_max_px, step)
    y_starts = _starts(height, tile_max_px, step)
    for y1 in y_starts:
        for x1 in x_starts:
            x2 = min(width, x1 + tile_max_px)
            y2 = min(height, y1 + tile_max_px)
            bbox = clamp_bbox((x1, y1, x2, y2), width=width, height=height)
            patch_id = f"tile-{bbox[1]}-{bbox[0]}-{bbox[3]}-{bbox[2]}"
            tiles.append(_make_patch(patch_id, bbox, image_rgb))
    if focus_tokens and focus_max_patches != 0:
        focus_boxes = _focus_bboxes(
            focus_tokens,
            width=width,
            height=height,
            conf_bp=focus_conf_bp,
            cluster_gap_px=focus_cluster_gap_px,
        )
        if focus_max_patches > 0:
            focus_boxes = focus_boxes[:focus_max_patches]
        existing = {tuple(tile["bbox"]) for tile in tiles}
        for idx, bbox in enumerate(focus_boxes):
            expanded = _expand_bbox(bbox, focus_padding_px, width=width, height=height)
            if expanded in existing:
                continue
            patch_id = f"focus-{idx}-{expanded[1]}-{expanded[0]}-{expanded[3]}-{expanded[2]}"
            tiles.append(_make_patch(patch_id, expanded, image_rgb))
            existing.add(expanded)
    tiles.sort(key=lambda t: (t["bbox"][1], t["bbox"][0], -(t["bbox"][2] - t["bbox"][0]) * (t["bbox"][3] - t["bbox"][1]), t["patch_id"]))
    _ensure_coverage(tiles, width=width, height=height, add_full_frame=add_full_frame)
    _ensure_unique_ids(tiles)
    return tiles


def _pil():
    try:
        from PIL import Image as _Image
    except Exception as exc:  # pragma: no cover - dependency missing
        raise RuntimeError("Pillow is required for SST image processing") from exc
    return _Image


def _focus_bboxes(
    tokens: list[dict[str, Any]],
    *,
    width: int,
    height: int,
    conf_bp: int,
    cluster_gap_px: int,
) -> list[BBox]:
    if not tokens:
        return []
    selected: list[BBox] = []
    for token in tokens:
        bbox = token.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        try:
            conf = int(token.get("confidence_bp", 0))
        except Exception:
            conf = 0
        if conf_bp and conf >= conf_bp:
            continue
        try:
            bx = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
        except Exception:
            continue
        selected.append(clamp_bbox(bx, width=width, height=height))
    if not selected:
        return []
    selected.sort(key=lambda b: (b[1], b[0], b[3], b[2]))
    clusters: list[BBox] = []
    for bbox in selected:
        placed = False
        for idx, cluster in enumerate(clusters):
            if _bbox_close(cluster, bbox, gap=cluster_gap_px):
                clusters[idx] = _bbox_union(cluster, bbox)
                placed = True
                break
        if not placed:
            clusters.append(bbox)
    clusters.sort(key=lambda b: (b[1], b[0], b[3], b[2]))
    return clusters


def _bbox_close(a: BBox, b: BBox, *, gap: int) -> bool:
    return not (a[2] + gap < b[0] or b[2] + gap < a[0] or a[3] + gap < b[1] or b[3] + gap < a[1])


def _bbox_union(a: BBox, b: BBox) -> BBox:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _expand_bbox(bbox: BBox, padding_px: int, *, width: int, height: int) -> BBox:
    x1, y1, x2, y2 = bbox
    pad = max(0, int(padding_px))
    return clamp_bbox((x1 - pad, y1 - pad, x2 + pad, y2 + pad), width=width, height=height)


def _make_patch(patch_id: str, bbox: BBox, image_rgb: PILImage) -> dict[str, Any]:
    x1, y1, x2, y2 = bbox
    patch = image_rgb.crop((x1, y1, x2, y2))
    buf = BytesIO()
    patch.save(buf, format="PNG")
    return {
        "patch_id": patch_id,
        "bbox": (x1, y1, x2, y2),
        "image_rgb": patch,
        "image_bytes": buf.getvalue(),
        "width": int(x2 - x1),
        "height": int(y2 - y1),
    }


def _starts(limit: int, size: int, step: int) -> list[int]:
    if limit <= size:
        return [0]
    starts = list(range(0, max(1, limit - size + 1), step))
    last = limit - size
    if not starts or starts[-1] != last:
        starts.append(last)
    return starts


def _ensure_coverage(tiles: list[dict[str, Any]], *, width: int, height: int, add_full_frame: bool) -> None:
    if add_full_frame:
        return
    # Cheap coverage check using a coarse grid.
    step_x = max(1, width // 32)
    step_y = max(1, height // 32)
    covered = set()
    for tile in tiles:
        x1, y1, x2, y2 = tile["bbox"]
        for yy in range(y1, y2, step_y):
            for xx in range(x1, x2, step_x):
                covered.add((xx // step_x, yy // step_y))
    total = (width + step_x - 1) // step_x * ((height + step_y - 1) // step_y)
    if len(covered) < total:
        raise RuntimeError("Tile coverage incomplete")


def _ensure_unique_ids(tiles: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for tile in tiles:
        pid = str(tile.get("patch_id", ""))
        if not pid:
            raise RuntimeError("Missing patch_id")
        if pid in seen:
            raise RuntimeError(f"Duplicate patch_id: {pid}")
        seen.add(pid)


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    data = sorted(values)
    mid = len(data) // 2
    if len(data) % 2:
        return float(data[mid])
    return float((data[mid - 1] + data[mid]) / 2.0)


def _dct_1d(vec: list[float]) -> list[float]:
    n = len(vec)
    if n == 0:
        return []
    cos_table = _cos_table(n)
    out: list[float] = []
    for k in range(n):
        total = 0.0
        row = cos_table[k]
        for i, val in enumerate(vec):
            total += float(val) * row[i]
        out.append(total)
    return out


@lru_cache(maxsize=8)
def _cos_table(n: int) -> tuple[tuple[float, ...], ...]:
    table = []
    for k in range(n):
        row = [math.cos(math.pi / n * (i + 0.5) * k) for i in range(n)]
        table.append(tuple(row))
    return tuple(table)


def _dct_2d(mat: list[list[float]]) -> list[list[float]]:
    if not mat:
        return []
    # Apply separable DCT: rows then columns.
    row_dct = [_dct_1d(list(row)) for row in mat]
    n = len(row_dct)
    m = len(row_dct[0]) if row_dct else 0
    cols: list[list[float]] = [[row_dct[y][x] for y in range(n)] for x in range(m)]
    col_dct = [_dct_1d(col) for col in cols]
    out: list[list[float]] = [[0.0 for _x in range(m)] for _y in range(n)]
    for x in range(m):
        for y in range(n):
            out[y][x] = col_dct[x][y]
    return out
