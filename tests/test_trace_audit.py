import csv
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ais_etr.trace_audit import trace_no_match_candidates_against_upstream


class TraceAuditTests(unittest.TestCase):
    def test_trace_no_match_candidates_against_upstream_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = root / "upstream.xlsx"
            pd.DataFrame(
                [
                    {
                        "PEANO": "6101",
                        "Feeder ID": "PFA04",
                        "TX: Feeder": "PFA04",
                        "TX: FACILITYID": "TX-1",
                        "TX: PEANO": "TXP-1",
                        "RC: FACILITYID": "",
                        "SW: FACILITYID": "",
                        "CB: FACILITYID": "PFA04VB-01",
                        "status": "OK",
                        "district": "Phang Khon",
                    },
                    {
                        "PEANO": "6102",
                        "Feeder ID": "PFA03",
                        "TX: Feeder": "PFA03",
                        "TX: FACILITYID": "TX-2",
                        "TX: PEANO": "TXP-2",
                        "RC: FACILITYID": "PFA03VR-101",
                        "SW: FACILITYID": "",
                        "CB: FACILITYID": "",
                        "status": "OK",
                        "district": "Phang Khon",
                    },
                ]
            ).to_excel(upstream, sheet_name="Upstream Trace", index=False)
            candidates = root / "candidates.csv"
            with candidates.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["priority_rank", "device_type", "device_id", "feeder", "event_count"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "priority_rank": "1",
                        "device_type": "CB",
                        "device_id": "PFA04VB-01",
                        "feeder": "PFA04",
                        "event_count": "3",
                    }
                )
                writer.writerow(
                    {
                        "priority_rank": "2",
                        "device_type": "CB",
                        "device_id": "PFA05VB-01",
                        "feeder": "PFA05",
                        "event_count": "2",
                    }
                )
            output = root / "trace.csv"
            markdown = root / "trace.md"

            result = trace_no_match_candidates_against_upstream(candidates, upstream, output, markdown)

            self.assertEqual(result["candidates"], 2)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["upstream_trace_result"], "source_traces_device_to_confident_ais")
            self.assertEqual(rows[0]["expected_device_ok_rows"], "1")
            self.assertEqual(
                rows[1]["upstream_trace_result"],
                "no_source_evidence_on_candidate_feeder_same_station_has_ais",
            )
            self.assertNotIn("PEANO", rows[0])
            self.assertNotIn("raw_text", rows[0])
            self.assertTrue(markdown.exists())


if __name__ == "__main__":
    unittest.main()
