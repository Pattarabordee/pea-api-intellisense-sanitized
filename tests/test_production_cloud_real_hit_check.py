import unittest
from pathlib import Path


class ProductionCloudRealHitCheckTests(unittest.TestCase):
    def test_guard_writes_only_redacted_private_reports_and_does_not_probe_public_console(self):
        script = (Path(__file__).resolve().parents[1] / "runtime" / "production_cloud_real_hit_check.ps1").read_text(encoding="utf-8")

        self.assertIn('"runtime/private/production_cloud_real_hit_status.json"', script)
        self.assertIn('"runtime/private/production_cloud_real_hit_status.md"', script)
        self.assertIn("function Get-RedactedRequestRef", script)
        self.assertIn("REDACTED_REQUEST_REF_ONLY", script)
        self.assertIn("requestRef = [string]$latest.request_ref", script)
        self.assertIn("requestRef = Get-RedactedRequestRef", script)
        self.assertIn("request_ref = $requestRef", script)
        self.assertIn('"- request_ref: "', script)
        self.assertNotIn('"- request_id: "', script)
        self.assertNotIn("request_id =", script)
        self.assertNotIn("web_console_live_data", script)
        self.assertNotIn("WebUrl", script)
        self.assertNotIn("curl.exe", script)
        self.assertIn("SKIPPED_DEMO_ISOLATED", script)


if __name__ == "__main__":
    unittest.main()
