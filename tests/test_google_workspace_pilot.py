from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "runtime" / "google_workspace_pilot"


class GoogleWorkspacePilotPackageTests(unittest.TestCase):
    def test_apps_script_source_is_retained_only_as_a_superseded_reference(self):
        code = (PACKAGE / "Code.gs").read_text(encoding="utf-8")
        self.assertIn("SUPERSEDED", code)
        self.assertIn('const MODE = "shadow";', code)
        self.assertIn('const PRODUCTION_SEND = "blocked";', code)
        self.assertNotRegex(code, re.compile(r"sk-[A-Za-z0-9_-]{12,}"))
        self.assertNotRegex(code, re.compile(r"Y2lzY29zcGFyazovL3VzL1JPT00v[A-Za-z0-9_=-]+"))
        self.assertNotRegex(code, re.compile(r"AIza[0-9A-Za-z_-]{20,}"))

    def test_docs_mark_the_legacy_pilot_as_not_deployable(self):
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
        deployment = (PACKAGE / "deployment_note.md").read_text(encoding="utf-8")
        checklist = (PACKAGE / "setup_checklist.md").read_text(encoding="utf-8")
        self.assertIn("Superseded", readme)
        self.assertIn("Do not deploy", readme)
        self.assertIn("Superseded", deployment)
        self.assertIn("Superseded", checklist)
        self.assertIn("X-API-Key", readme)
        self.assertNotIn("pilot_key=", readme)
        self.assertNotIn("Deploy >", checklist)


if __name__ == "__main__":
    unittest.main()
