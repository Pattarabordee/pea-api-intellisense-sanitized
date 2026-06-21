from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "runtime" / "google_workspace_pilot"


class GoogleWorkspacePilotPackageTests(unittest.TestCase):
    def test_apps_script_package_has_shadow_guardrails_and_required_handlers(self):
        code = (PACKAGE / "Code.gs").read_text(encoding="utf-8")
        required_markers = [
            "function doPost(e)",
            "function doGet(e)",
            "function setupPilotSheets()",
            "mode: MODE",
            "production_send: PRODUCTION_SEND",
            "http_status: 202",
            "DUPLICATE_REQUEST",
            "pilot_key",
            "Apps Script direct web apps cannot set custom HTTP 202/401 or read X-API-Key headers",
        ]
        for marker in required_markers:
            self.assertIn(marker, code)
        self.assertIn('const MODE = "shadow";', code)
        self.assertIn('const PRODUCTION_SEND = "blocked";', code)
        self.assertNotRegex(code, re.compile(r"sk-[A-Za-z0-9_-]{12,}"))
        self.assertNotRegex(code, re.compile(r"Y2lzY29zcGFyazovL3VzL1JPT00v[A-Za-z0-9_=-]+"))
        self.assertNotRegex(code, re.compile(r"AIza[0-9A-Za-z_-]{20,}"))

    def test_docs_and_template_files_exist_and_warn_about_apps_script_limits(self):
        for name in [
            "README.md",
            "setup_checklist.md",
            "sheet_schema.md",
            "test_request.json",
            "appsscript.json",
            "build_sheet_template.mjs",
        ]:
            self.assertTrue((PACKAGE / name).exists(), name)
        readme = (PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertIn("zero-cost cloud pilot / shadow mode", readme)
        self.assertIn("production_send = blocked", readme)
        self.assertIn("X-API-Key", readme)
        self.assertIn("pilot_key", readme)
        self.assertIn("HTTP status", readme)
        self.assertNotIn("https://<REDACTED_TUNNEL>", readme)


if __name__ == "__main__":
    unittest.main()
