from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest


def _load_module():
    path = pathlib.Path("tools/build_query_stress_pack.py")
    spec = importlib.util.spec_from_file_location("build_query_stress_pack_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BuildQueryStressPackDefaultTests(unittest.TestCase):
    def test_default_sources_include_temporal_qa40(self) -> None:
        mod = _load_module()
        sources = list(getattr(mod, "DEFAULT_SOURCES", []))
        self.assertIn("docs/query_eval_cases_temporal_screenshot_qa_40.json", sources)


if __name__ == "__main__":
    unittest.main()

