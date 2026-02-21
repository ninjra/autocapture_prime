import unittest

from autocapture_nx.ux.facade import _apply_revert_patch, _is_deleted_marker, _snapshot_patch_values, _deleted_marker


class ConfigHistoryTests(unittest.TestCase):
    def test_snapshot_patch_values_marks_missing(self) -> None:
        current = {"privacy": {"egress": {"enabled": True}}}
        patch = {"privacy": {"egress": {"enabled": False}}, "new": {"flag": True}}
        snapshot = _snapshot_patch_values(current, patch)
        self.assertEqual(snapshot["privacy"]["egress"]["enabled"], True)
        self.assertTrue(_is_deleted_marker(snapshot["new"]["flag"]))

    def test_apply_revert_patch_removes_deleted(self) -> None:
        target = {"privacy": {"egress": {"enabled": False}}, "new": {"flag": True}}
        revert = {"privacy": {"egress": {"enabled": True}}, "new": {"flag": _deleted_marker()}}
        _apply_revert_patch(target, revert)
        self.assertEqual(target["privacy"]["egress"]["enabled"], True)
        self.assertNotIn("flag", target.get("new", {}))


if __name__ == "__main__":
    unittest.main()
