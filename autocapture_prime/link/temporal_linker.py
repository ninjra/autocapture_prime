from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from autocapture_prime.layout.base import UiElement


@dataclass(frozen=True)
class TrackedElement:
    track_id: str
    frame_index: int
    element_id: str
    type: str
    text: str
    bbox: tuple[int, int, int, int]


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0 = max(ax0, bx0)
    iy0 = max(ay0, by0)
    ix1 = min(ax1, bx1)
    iy1 = min(ay1, by1)
    iw = max(0, ix1 - ix0)
    ih = max(0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0, ax1 - ax0) * max(0, ay1 - ay0)
    area_b = max(0, bx1 - bx0) * max(0, by1 - by0)
    union = area_a + area_b - inter
    return float(inter) / float(union) if union else 0.0


class TemporalLinker:
    def __init__(self, iou_threshold: float = 0.3) -> None:
        self.iou_threshold = float(iou_threshold)

    def link(
        self,
        frames: list[tuple[int, list[UiElement]]],
        click_points: dict[int, tuple[int, int]] | None = None,
    ) -> tuple[list[TrackedElement], int]:
        click_points = click_points or {}
        tracks: list[TrackedElement] = []
        prev: dict[str, UiElement] = {}
        next_track = 1
        id_switches = 0

        for frame_index, elements in frames:
            current_map: dict[str, UiElement] = {}
            used_prev: set[str] = set()
            for element in elements:
                chosen: str | None = None
                best_score = -1.0
                for prev_track, prev_elem in prev.items():
                    if prev_track in used_prev:
                        continue
                    if prev_elem.type != element.type:
                        continue
                    iou = _iou(prev_elem.bbox, element.bbox)
                    if iou < self.iou_threshold:
                        continue
                    text_score = SequenceMatcher(None, prev_elem.text or "", element.text or "").ratio()
                    click_boost = 0.0
                    click = click_points.get(frame_index)
                    if click and _contains(element.bbox, click):
                        click_boost = 0.2
                    score = (0.7 * iou) + (0.3 * text_score) + click_boost
                    if score > best_score:
                        best_score = score
                        chosen = prev_track
                if chosen is None:
                    chosen = f"trk_{next_track:06d}"
                    next_track += 1
                else:
                    used_prev.add(chosen)
                    prev_elem = prev.get(chosen)
                    if prev_elem and prev_elem.element_id != element.element_id:
                        id_switches += 1
                current_map[chosen] = element
                tracks.append(
                    TrackedElement(
                        track_id=chosen,
                        frame_index=frame_index,
                        element_id=element.element_id,
                        type=element.type,
                        text=element.text,
                        bbox=element.bbox,
                    )
                )
            prev = current_map
        return tracks, id_switches


def _contains(bbox: tuple[int, int, int, int], point: tuple[int, int]) -> bool:
    x0, y0, x1, y1 = bbox
    return x0 <= point[0] <= x1 and y0 <= point[1] <= y1
