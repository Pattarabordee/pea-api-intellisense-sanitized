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

    def test_tracked_status_snapshot_and_pitch_do_not_preserve_stale_raw_operational_claims(self):
        root = Path(__file__).resolve().parents[1]
        status_snapshot = (root / "runtime" / "production_cloud_real_hit_status.md").read_text(encoding="utf-8")
        pitch = (root / "runtime" / "pea_api_intellisense_pitch_answers.md").read_text(encoding="utf-8")

        self.assertIn("Superseded Cloud Hit Snapshot", status_snapshot)
        self.assertIn("runtime/private/", status_snapshot)
        self.assertNotIn("request_id", status_snapshot)
        self.assertNotIn("AIS-CLOUD-", status_snapshot)
        self.assertIn("authenticated GET-only guard", pitch)
        self.assertIn("hash reference", pitch)
        self.assertNotIn("AIS-20260621-0001", pitch)
        self.assertNotIn("non_smoke_requests = 4", pitch)


if __name__ == "__main__":
    unittest.main()
