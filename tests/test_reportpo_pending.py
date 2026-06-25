import csv
import json
import tempfile
import unittest
from pathlib import Path

from ais_etr.db import RuntimeDb
from ais_etr.reportpo_pending import (
    PENDING_COLUMNS,
    audit_reportpo_pending_overlap,
    build_reportpo_pending_query,
    import_reportpo_pending,
)
from ais_etr.schemas import OutageDevice, OutageEvent


class ReportPoPendingTests(unittest.TestCase):
    def test_build_pending_query_uses_pending_entity_and_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.json"
            template.write_text(
                json.dumps([{"request": json.dumps({"modelId": "205564749", "userPreferredLocale": "en-US"})}]),
                encoding="utf-8",
            )

            built = build_reportpo_pending_query(template, count=5000, restart_tokens=[["token-1"]])
            command = built["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]

            self.assertEqual(command["Query"]["From"], [{"Name": "p", "Entity": "Pending", "Type": 0}])
            properties = [item["Column"]["Property"] for item in command["Query"]["Select"]]
            self.assertIn("EVENT_ID", properties)
            self.assertIn("DEVICE_NAME", properties)
            self.assertIn("EVENT_STATUS2", properties)
            self.assertEqual(command["Query"]["OrderBy"][0]["Expression"]["Column"]["Property"], "YYYY_MM")
            self.assertEqual(command["Binding"]["DataReduction"]["Primary"]["Window"]["Count"], 5000)

    def test_import_pending_querydata_decodes_status_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "pending.json"
            output = root / "pending.csv"
            select = [
                _select("G0", "EVENT_ID"),
                _select("G1", "DEVICE_NAME"),
                _select("G2", "YYYY"),
                _select("G3", "YYYY_MM"),
                _select("G4", "EVENT_TYPE"),
                _select("G5", "EVENT_STATUS"),
                _select("G6", "EVENT_TYPE2"),
                _select("G7", "EVENT_STATUS2"),
            ]
            schema = [
                {"N": "G0", "T": 1, "DN": "D0"},
                {"N": "G1", "T": 1, "DN": "D1"},
                {"N": "G2", "T": 4},
                {"N": "G3", "T": 1, "DN": "D2"},
                {"N": "G4", "T": 1, "DN": "D3"},
                {"N": "G5", "T": 1, "DN": "D4"},
                {"N": "G6", "T": 1, "DN": "D5"},
                {"N": "G7", "T": 1, "DN": "D6"},
            ]
            response = {
                "results": [
                    {
                        "result": {
                            "data": {
                                "descriptor": {"Select": select},
                                "dsr": {
                                    "DS": [
                                        {
                                            "PH": [{"DM0": [{"S": schema, "C": [0, 0, 2026, 0, 0, 0, 0, 0]}]}],
                                            "ValueDicts": {
                                                "D0": ["6847000001"],
                                                "D1": ["PFA01R-01"],
                                                "D2": ["2026-06"],
                                                "D3": ["OU"],
                                                "D4": ["IP"],
                                                "D5": ["ไฟฟ้าขัดข้อง"],
                                                "D6": ["อยู่ระหว่างดำเนินการ"],
                                            },
                                        }
                                    ]
                                },
                            }
                        }
                    }
                ]
            }
            source.write_text(json.dumps([{"response": json.dumps(response)}]), encoding="utf-8")

            result = import_reportpo_pending(source, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["rows"], 1)
            self.assertEqual(rows[0]["event_number"], "6847000001")
            self.assertEqual(rows[0]["device_id"], "PFA01R-01")
            self.assertEqual(rows[0]["feeder"], "PFA01")
            self.assertEqual(rows[0]["event_status"], "IP")
            self.assertEqual(rows[0]["event_status2"], "อยู่ระหว่างดำเนินการ")

    def test_pending_overlap_prefers_event_number_then_device_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, event_time="2026-06-17T10:03:00", device_id="PFA01R-01")
            pending = root / "pending.csv"
            _write_pending(
                pending,
                [
                    {"event_number": "6847000001", "device_id": "PFA01R-01", "feeder": "PFA01"},
                    {"event_number": "6847000002", "device_id": "PFA02R-01", "feeder": "PFA02"},
                ],
            )
            feature = root / "feature.csv"
            with feature.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["event_number", "webex_message_id", "webex_device_id", "match_status"],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "event_number": "6847000001",
                        "webex_message_id": "msg-1",
                        "webex_device_id": "PFA01R-01",
                        "match_status": "matched",
                    }
                )
            output = root / "overlap.csv"

            result = audit_reportpo_pending_overlap(db.path, pending, feature, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["overlap_status"]["event_number_overlap"], 1)
            self.assertEqual(result["overlap_status"]["no_overlap"], 1)
            self.assertEqual(rows[0]["overlap_status"], "event_number_overlap")


def _select(name: str, property_name: str) -> dict:
    return {
        "Kind": 1,
        "Value": name,
        "GroupKeys": [
            {
                "Source": {"Entity": "Pending", "Property": property_name},
                "Calc": name,
                "IsSameAsSelect": True,
            }
        ],
        "Name": f"Pending.{property_name}",
    }


def _runtime_db_with_event(root: Path, event_time: str, device_id: str) -> RuntimeDb:
    db = RuntimeDb(root / "runtime.sqlite")
    db.init()
    db.insert_webex_message({"id": "msg-1", "roomId": "room-1", "created": event_time, "text": "event"})
    db.upsert_event(
        OutageEvent(
            event_id="event-1",
            source="webex",
            webex_message_id="msg-1",
            room_id="room-1",
            raw_text="event",
            event_time=event_time,
            outage_device=OutageDevice(device_type="Recloser", device_id=device_id, feeder=device_id[:5]),
        )
    )
    return db


def _write_pending(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PENDING_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in PENDING_COLUMNS})


if __name__ == "__main__":
    unittest.main()
