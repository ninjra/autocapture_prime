import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


class OptionalDepsImportTests(unittest.TestCase):
    def test_optional_extras_declared(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pyproject = root / "pyproject.toml"
        data = pyproject.read_text(encoding="utf-8")
        try:
            import tomllib  # type: ignore
        except ModuleNotFoundError:
            tomllib = None
        if tomllib is None:
            # Fallback: simple string checks when tomllib is unavailable.
            for key in ("embeddings", "vision", "sqlcipher"):
                self.assertIn(f"{key} = [", data)
            return
        payload = tomllib.loads(data)
        extras = payload.get("project", {}).get("optional-dependencies", {})
        self.assertIn("embeddings", extras)
        self.assertIn("vision", extras)
        self.assertIn("sqlcipher", extras)

    def test_imports_do_not_pull_heavy_deps(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = textwrap.dedent(
            """
            import importlib
            import sys

            heavy = {"torch", "transformers", "sentence_transformers"}
            modules = [
                "autocapture_nx.kernel.loader",
                "autocapture.capture.pipelines",
                "autocapture.capture.spool",
                "autocapture.ingest",
                "autocapture.runtime.governor",
                "autocapture.runtime.scheduler",
                "autocapture.indexing.vector",
                "autocapture.memory.answer_orchestrator",
            ]

            for name in modules:
                importlib.import_module(name)

            loaded = sorted([name for name in heavy if name in sys.modules])
            if loaded:
                print("loaded_heavy=" + ",".join(loaded))
                raise SystemExit(1)
            """
        ).strip()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root)
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            output = (result.stdout + "\n" + result.stderr).strip()
            self.fail(f"Heavy deps imported during baseline imports: {output}")


if __name__ == "__main__":
    unittest.main()
