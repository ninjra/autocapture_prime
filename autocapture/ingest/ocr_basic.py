"""Lightweight OCR utilities with deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont, ImageOps

_GLYPH_SIZE = (12, 16)
_GLYPH_CHARS = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    ".,:;!?/\\-_=+()[]{}<>@#$%&"
)


@dataclass(frozen=True)
class OCRToken:
    text: str
    bbox: tuple[int, int, int, int]
    confidence: float


_GLYPH_CACHE: dict[str, tuple[int, ...]] | None = None


def ocr_tokens_from_bytes(image_bytes: bytes) -> list[OCRToken]:
    if not image_bytes:
        return []
    try:
        image = Image.open(_as_bytes_io(image_bytes)).convert("RGB")
    except Exception:
        return []
    return ocr_tokens_from_image(image)


def ocr_text_from_bytes(image_bytes: bytes) -> str:
    tokens = ocr_tokens_from_bytes(image_bytes)
    return _tokens_to_text(tokens)


def ocr_text_from_image(image: Image.Image) -> str:
    tokens = ocr_tokens_from_image(image)
    return _tokens_to_text(tokens)


def ocr_tokens_from_image(image: Image.Image) -> list[OCRToken]:
    tokens = _tesseract_tokens(image)
    if tokens is not None:
        return tokens
    return _basic_tokens(image)


def _tesseract_tokens(image: Image.Image) -> list[OCRToken] | None:
    try:
        import pytesseract
    except Exception:
        return None
    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    except Exception:
        return None
    results: list[OCRToken] = []
    width, height = image.size
    texts = data.get("text", [])
    confs = data.get("conf", [])
    lefts = data.get("left", [])
    tops = data.get("top", [])
    widths = data.get("width", [])
    heights = data.get("height", [])
    for idx, text in enumerate(texts):
        if not text or not str(text).strip():
            continue
        try:
            x0 = int(lefts[idx])
            y0 = int(tops[idx])
            w = int(widths[idx])
            h = int(heights[idx])
            conf = float(confs[idx]) / 100.0 if confs else 0.0
        except Exception:
            continue
        x1 = min(width, x0 + max(0, w))
        y1 = min(height, y0 + max(0, h))
        results.append(OCRToken(text=str(text), bbox=(x0, y0, x1, y1), confidence=max(0.0, min(1.0, conf))))
    return results


def _basic_tokens(image: Image.Image) -> list[OCRToken]:
    img = image.convert("L")
    width, height = img.size
    scale = 1.0
    max_dim = 640
    if max(width, height) > max_dim:
        scale = max_dim / float(max(width, height))
        resized = (max(1, int(width * scale)), max(1, int(height * scale)))
        img = img.resize(resized, Image.BILINEAR)
        width, height = img.size

    img = _normalize_contrast(img)
    bw = _binarize(img)
    components = _find_components(bw)
    if not components:
        return []

    chars: list[_CharBox] = []
    for comp in components:
        x0, y0, x1, y1 = comp
        crop = bw.crop((x0, y0, x1 + 1, y1 + 1))
        char, score = _match_glyph(crop)
        if not char:
            char = "?"
            conf = min(0.2, float(score))
        else:
            conf = float(score)
        conf = max(0.0, min(1.0, conf))
        if scale != 1.0:
            x0 = int(x0 / scale)
            y0 = int(y0 / scale)
            x1 = int(x1 / scale)
            y1 = int(y1 / scale)
        chars.append(_CharBox(char, conf, (x0, y0, x1, y1)))

    return _chars_to_tokens(chars)


def _normalize_contrast(img: Image.Image) -> Image.Image:
    hist = img.histogram()
    total = sum(hist) or 1
    mean = sum(idx * count for idx, count in enumerate(hist)) / total
    if mean < 96:
        img = ImageOps.invert(img)
    return img


def _binarize(img: Image.Image) -> Image.Image:
    hist = img.histogram()
    total = sum(hist) or 1
    sum_total = sum(i * hist[i] for i in range(256))
    sum_back = 0.0
    weight_back = 0.0
    max_between = -1.0
    threshold = 128
    for i in range(256):
        weight_back += hist[i]
        if weight_back == 0:
            continue
        weight_fore = total - weight_back
        if weight_fore == 0:
            break
        sum_back += i * hist[i]
        mean_back = sum_back / weight_back
        mean_fore = (sum_total - sum_back) / weight_fore
        between = weight_back * weight_fore * (mean_back - mean_fore) ** 2
        if between > max_between:
            max_between = between
            threshold = i
    return img.point(lambda p: 0 if p < threshold else 255, mode="L")


def _find_components(bw: Image.Image) -> list[tuple[int, int, int, int]]:
    width, height = bw.size
    pix = bw.load()
    visited = [bytearray(width) for _ in range(height)]
    components: list[tuple[int, int, int, int]] = []
    min_area = max(6, (width * height) // 20000)

    for y in range(height):
        row = visited[y]
        for x in range(width):
            if row[x] or pix[x, y] != 0:
                continue
            stack = [(x, y)]
            row[x] = 1
            min_x = max_x = x
            min_y = max_y = y
            area = 0
            while stack:
                cx, cy = stack.pop()
                area += 1
                if cx < min_x:
                    min_x = cx
                if cx > max_x:
                    max_x = cx
                if cy < min_y:
                    min_y = cy
                if cy > max_y:
                    max_y = cy
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    if visited[ny][nx]:
                        continue
                    if pix[nx, ny] != 0:
                        continue
                    visited[ny][nx] = 1
                    stack.append((nx, ny))
            if area >= min_area:
                components.append((min_x, min_y, max_x, max_y))
    return components


def _glyph_cache() -> dict[str, tuple[int, ...]]:
    global _GLYPH_CACHE
    if _GLYPH_CACHE is not None:
        return _GLYPH_CACHE
    font = ImageFont.load_default()
    cache: dict[str, tuple[int, ...]] = {}
    for ch in _GLYPH_CHARS:
        img = Image.new("L", _GLYPH_SIZE, 255)
        draw = ImageDraw.Draw(img)
        draw.text((0, 0), ch, font=font, fill=0)
        cache[ch] = _image_bits(img)
    _GLYPH_CACHE = cache
    return cache


def _image_bits(img: Image.Image) -> tuple[int, ...]:
    img = img.convert("L")
    bw = img.point(lambda p: 0 if p < 128 else 255, mode="L")
    data = bw.get_flattened_data() if hasattr(bw, "get_flattened_data") else bw.getdata()
    return tuple(1 if p == 0 else 0 for p in data)


def _match_glyph(img: Image.Image) -> tuple[str | None, float]:
    glyphs = _glyph_cache()
    resized = img.resize(_GLYPH_SIZE, Image.NEAREST)
    bits = _image_bits(resized)
    total = len(bits) or 1
    best_char: str | None = None
    best_score = 0.0
    for ch, tmpl in glyphs.items():
        match = sum(1 for a, b in zip(bits, tmpl) if a == b) / total
        if match > best_score:
            best_char = ch
            best_score = match
    if best_score < 0.8:
        return None, best_score
    return best_char, best_score


@dataclass(frozen=True)
class _CharBox:
    text: str
    confidence: float
    bbox: tuple[int, int, int, int]

    @property
    def cx(self) -> int:
        return (self.bbox[0] + self.bbox[2]) // 2

    @property
    def cy(self) -> int:
        return (self.bbox[1] + self.bbox[3]) // 2

    @property
    def width(self) -> int:
        return max(1, self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> int:
        return max(1, self.bbox[3] - self.bbox[1])


def _chars_to_tokens(chars: list[_CharBox]) -> list[OCRToken]:
    if not chars:
        return []
    heights = sorted(c.height for c in chars)
    median_h = heights[len(heights) // 2] if heights else 12
    line_thresh = max(4, median_h // 2)

    lines: list[list[_CharBox]] = []
    line_centers: list[int] = []
    for char in sorted(chars, key=lambda c: (c.cy, c.cx)):
        placed = False
        for idx, center in enumerate(line_centers):
            if abs(char.cy - center) <= line_thresh:
                lines[idx].append(char)
                line_centers[idx] = int((center * (len(lines[idx]) - 1) + char.cy) / len(lines[idx]))
                placed = True
                break
        if not placed:
            lines.append([char])
            line_centers.append(char.cy)

    tokens: list[OCRToken] = []
    for line in lines:
        ordered = sorted(line, key=lambda c: c.bbox[0])
        widths = sorted(c.width for c in ordered)
        median_w = widths[len(widths) // 2] if widths else 8
        gap_thresh = max(2, int(median_w * 0.75))
        current: list[_CharBox] = []
        prev: _CharBox | None = None
        for ch in ordered:
            if prev is None:
                current = [ch]
            else:
                gap = ch.bbox[0] - prev.bbox[2]
                if gap > gap_thresh:
                    tokens.extend(_word_tokens(current))
                    current = [ch]
                else:
                    current.append(ch)
            prev = ch
        tokens.extend(_word_tokens(current))
    return tokens


def _word_tokens(chars: Iterable[_CharBox]) -> list[OCRToken]:
    chars = list(chars)
    if not chars:
        return []
    text = "".join(ch.text for ch in chars)
    x0 = min(ch.bbox[0] for ch in chars)
    y0 = min(ch.bbox[1] for ch in chars)
    x1 = max(ch.bbox[2] for ch in chars)
    y1 = max(ch.bbox[3] for ch in chars)
    conf = sum(ch.confidence for ch in chars) / max(1, len(chars))
    return [OCRToken(text=text, bbox=(x0, y0, x1, y1), confidence=conf)]


def _tokens_to_text(tokens: list[OCRToken]) -> str:
    if not tokens:
        return ""
    lines: dict[int, list[OCRToken]] = {}
    for token in tokens:
        line_key = token.bbox[1] // 10
        lines.setdefault(line_key, []).append(token)
    out_lines: list[str] = []
    for key in sorted(lines.keys()):
        line_tokens = sorted(lines[key], key=lambda t: t.bbox[0])
        out_lines.append(" ".join(t.text for t in line_tokens if t.text.strip()))
    return "\n".join(line for line in out_lines if line.strip())


def _as_bytes_io(data: bytes):
    from io import BytesIO

    return BytesIO(data)
