import json
import unittest
from pathlib import Path

from autocapture_nx.kernel.config import SchemaLiteValidator


class ConfigDefaultsTests(unittest.TestCase):
    def test_default_config_validates(self) -> None:
        config = json.loads(Path("config/default.json").read_text(encoding="utf-8"))
        schema = json.loads(Path("contracts/config_schema.json").read_text(encoding="utf-8"))
        validator = SchemaLiteValidator()
        validator.validate(schema, config)


if __name__ == "__main__":
    unittest.main()
