import unittest

from autocapture.ux.facade import create_facade


class DoctorReportSchemaTests(unittest.TestCase):
    def test_doctor_report_schema(self) -> None:
        facade = create_facade()
        report = facade.doctor_report().to_dict()
        self.assertIn("ok", report)
        self.assertIn("generated_at_utc", report)
        self.assertIn("checks", report)


if __name__ == "__main__":
    unittest.main()
