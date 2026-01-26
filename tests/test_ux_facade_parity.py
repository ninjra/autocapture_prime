import unittest

from autocapture.ux.facade import create_facade
from autocapture.ux.settings_schema import get_schema


class UXFacadeParityTests(unittest.TestCase):
    def test_settings_schema_matches(self) -> None:
        facade = create_facade()
        self.assertEqual(facade.settings_schema(), get_schema())


if __name__ == "__main__":
    unittest.main()
