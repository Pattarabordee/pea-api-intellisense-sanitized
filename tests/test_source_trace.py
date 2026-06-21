import csv
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ais_etr.source_trace import trace_no_match_candidates_from_source_system


class FakeTraceClient:
    def __init__(self, layer_responses, trace_response):
        self.layer_responses = layer_responses
        self.trace_response = trace_response
        self.queries = []
        self.traces = []

    def query_layer(self, layer_id, where, **kwargs):
        self.queries.append((layer_id, where, kwargs))
        return self.layer_responses.get(layer_id, {"features": []})

    def trace_downstream(self, geometry):
        self.traces.append(geometry)
        return self.trace_response


class SourceTraceTests(unittest.TestCase):
    def test_source_trace_confirms_confident_ais_downstream_without_exporting_peano_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = _write_upstream(root, [{"PEANO": "6101", "Feeder ID": "PFA04", "status": "OK"}])
            candidates = _write_candidates(
                root,
                [{"priority_rank": "1", "device_type": "CB", "device_id": "PFA04VB-01", "feeder": "PFA04", "event_count": "3"}],
            )
            client = FakeTraceClient(
                {
                    11: {
                        "features": [
                            {
                                "attributes": {
                                    "OBJECTID": 1,
                                    "FACILITYID": "PFA04VB-01",
                                    "FEEDERID": "PFA04",
                                    "LOCATION": "PFA",
                                },
                                "geometry": {"x": 1, "y": 2, "spatialReference": {"wkid": 102100}},
                            }
                        ]
                    }
                },
                {
                    "success": True,
                    "traceResult": [
                        {
                            "name": "DS_LowVoltageMeter:meter",
                            "id": 25,
                            "features": [
                                {"attributes": {"OBJECTID": 10, "PEANO": "6101"}},
                                {"attributes": {"OBJECTID": 11, "PEANO": "9999"}},
                            ],
                        }
                    ],
                },
            )

            result = trace_no_match_candidates_from_source_system(
                candidates,
                upstream,
                root / "trace.csv",
                root / "trace.md",
                redacted_dir=root / "redacted",
                client=client,
            )

            self.assertEqual(result["ais_confident_hit_candidates"], 1)
            rows = _read_csv(root / "trace.csv")
            self.assertEqual(rows[0]["source_trace_result"], "source_trace_confirms_confident_ais_downstream")
            self.assertEqual(rows[0]["ais_confident_hits"], "1")
            self.assertNotIn("PEANO", rows[0])
            redacted_text = Path(rows[0]["redacted_trace_path"]).read_text(encoding="utf-8")
            self.assertNotIn("6101", redacted_text)
            self.assertNotIn("9999", redacted_text)
            self.assertIn("ais_confident_hits", redacted_text)

    def test_source_trace_keeps_no_meter_hits_non_confident(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = _write_upstream(
                root,
                [{"PEANO": "6102", "Feeder ID": "PFA04", "status": "NO_METER"}],
            )
            candidates = _write_candidates(
                root,
                [{"priority_rank": "1", "device_type": "CB", "device_id": "PFA04VB-01", "feeder": "PFA04", "event_count": "3"}],
            )
            client = FakeTraceClient(
                {
                    11: {
                        "features": [
                            {
                                "attributes": {"FACILITYID": "PFA04VB-01", "FEEDERID": "PFA04"},
                                "geometry": {"x": 1, "y": 2},
                            }
                        ]
                    }
                },
                {
                    "success": True,
                    "traceResult": [
                        {"name": "DS_LowVoltageMeter", "id": 25, "features": [{"attributes": {"PEANO": "6102"}}]}
                    ],
                },
            )

            trace_no_match_candidates_from_source_system(candidates, upstream, root / "trace.csv", client=client)

            rows = _read_csv(root / "trace.csv")
            self.assertEqual(rows[0]["source_trace_result"], "source_trace_finds_only_non_confident_ais_downstream")
            self.assertEqual(rows[0]["ais_confident_hits"], "0")
            self.assertEqual(rows[0]["ais_no_meter_hits"], "1")

    def test_source_trace_reports_device_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = _write_upstream(root, [{"PEANO": "6101", "Feeder ID": "PFA04", "status": "OK"}])
            candidates = _write_candidates(
                root,
                [{"priority_rank": "1", "device_type": "CB", "device_id": "PFA04VB-01", "feeder": "PFA04", "event_count": "3"}],
            )
            client = FakeTraceClient({}, {"success": True, "traceResult": []})

            trace_no_match_candidates_from_source_system(candidates, upstream, root / "trace.csv", client=client)

            rows = _read_csv(root / "trace.csv")
            self.assertEqual(rows[0]["source_trace_result"], "source_device_not_found")
            self.assertEqual(len(client.traces), 0)


def _write_upstream(root: Path, rows: list[dict[str, str]]) -> Path:
    path = root / "upstream.xlsx"
    normalized = []
    for row in rows:
        normalized.append(
            {
                "PEANO": row.get("PEANO", ""),
                "Feeder ID": row.get("Feeder ID", ""),
                "TX: Feeder": row.get("Feeder ID", ""),
                "TX: FACILITYID": "",
                "TX: PEANO": "",
                "RC: FACILITYID": "",
                "SW: FACILITYID": "",
                "CB: FACILITYID": "",
                "status": row.get("status", ""),
            }
        )
    pd.DataFrame(normalized).to_excel(path, sheet_name="Upstream Trace", index=False)
    return path


def _write_candidates(root: Path, rows: list[dict[str, str]]) -> Path:
    path = root / "candidates.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["priority_rank", "device_type", "device_id", "feeder", "event_count"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
