from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class DecodedFrame:
    frame_index: int
    image_path: Path
    width: int
    height: int
    mode: str


class FrameDecoder:
    """Decode PNG frame artifacts."""

    def decode_png(self, image_path: Path, frame_index: int) -> DecodedFrame:
        with Image.open(image_path) as image:
            width, height = image.size
            mode = image.mode
        return DecodedFrame(
            frame_index=int(frame_index),
            image_path=Path(image_path),
            width=int(width),
            height=int(height),
            mode=str(mode),
        )
