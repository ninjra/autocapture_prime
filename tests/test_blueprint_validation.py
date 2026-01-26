import unittest
from pathlib import Path

from tools import validate_blueprint


class BlueprintValidationTests(unittest.TestCase):
    def test_blueprint_is_valid(self) -> None:
        result = validate_blueprint.validate_blueprint(Path("BLUEPRINT.md"))
        if not result.ok:
            self.fail("; ".join(result.errors))


if __name__ == "__main__":
    unittest.main()
