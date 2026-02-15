from __future__ import annotations

import unittest

from autocapture_prime.layout.base import UiElement
from autocapture_prime.link.temporal_linker import TemporalLinker


class TemporalLinkerTests(unittest.TestCase):
    def test_link_is_deterministic_across_runs(self) -> None:
        frames = [
            (
                0,
                [
                    UiElement(
                        element_id="e1",
                        type="TEXT",
                        bbox=(10, 10, 80, 30),
                        confidence=0.9,
                        text="Inbox",
                    )
                ],
            ),
            (
                1,
                [
                    UiElement(
                        element_id="e2",
                        type="TEXT",
                        bbox=(12, 11, 82, 31),
                        confidence=0.9,
                        text="Inbox",
                    )
                ],
            ),
        ]
        linker = TemporalLinker(iou_threshold=0.1)
        first_tracks, first_switches = linker.link(frames, click_points={1: (20, 20)})
        second_tracks, second_switches = linker.link(frames, click_points={1: (20, 20)})
        self.assertEqual(first_switches, second_switches)
        self.assertEqual(
            [(row.track_id, row.frame_index, row.element_id) for row in first_tracks],
            [(row.track_id, row.frame_index, row.element_id) for row in second_tracks],
        )

    def test_link_handles_missing_click_points(self) -> None:
        frames = [
            (
                0,
                [
                    UiElement(
                        element_id="a1",
                        type="TEXT",
                        bbox=(0, 0, 40, 20),
                        confidence=0.7,
                        text="Chat",
                    )
                ],
            )
        ]
        linker = TemporalLinker(iou_threshold=0.1)
        tracks, switches = linker.link(frames)
        self.assertEqual(switches, 0)
        self.assertEqual(len(tracks), 1)
        self.assertTrue(tracks[0].track_id.startswith("trk_"))


if __name__ == "__main__":
    unittest.main()
