import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.source_trace_schematic import build_source_trace_schematic


class SourceTraceSchematicTests(unittest.TestCase):
    def test_schematic_renders_aggregate_counts_without_sensitive_terms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = root / "trace.csv"
            with audit.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "device_id",
                        "feeder",
                        "event_count",
                        "ais_confident_hits",
                        "source_trace_result",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "device_id": "PFA05VB-01",
                        "feeder": "PFA05",
                        "event_count": "7",
                        "ais_confident_hits": "6",
                        "source_trace_result": "source_trace_confirms_confident_ais_downstream",
                    }
                )
                writer.writerow(
                    {
                        "device_id": "PFA04VB-01",
                        "feeder": "PFA04",
                        "event_count": "14",
                        "ais_confident_hits": "0",
                        "source_trace_result": "source_trace_no_current_ais_downstream",
                    }
                )

            result = build_source_trace_schematic(audit, root / "schematic.md")

            text = (root / "schematic.md").read_text(encoding="utf-8-sig")
            self.assertEqual(result["total_candidates"], 2)
            self.assertIn("```mermaid", text)
            self.assertIn("PFA05VB-01 / PFA05", text)
            self.assertIn("Shadow / evidence only", text)
            for forbidden in ("token", "secret", "room_id", "refresh_token"):
                self.assertNotIn(forbidden, text.lower())


if __name__ == "__main__":
    unittest.main()
