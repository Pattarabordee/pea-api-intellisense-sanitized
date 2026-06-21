import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ais_etr.db import RuntimeDb
from ais_etr.reportpo_lifecycle import (
    REPORTPO_LIFECYCLE_COLUMNS,
    build_reportpo_lifecycle_query,
    import_reportpo_lifecycle,
    join_reportpo_lifecycle_to_shadow,
)
from ais_etr.schemas import OutageDevice, OutageEvent


def _ms(value: str) -> int:
    dt = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class ReportPoLifecycleTests(unittest.TestCase):
    def test_build_lifecycle_query_uses_po_entity_and_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.json"
            template.write_text(
                json.dumps([{"request": json.dumps({"modelId": "205564749", "userPreferredLocale": "en-US"})}]),
                encoding="utf-8",
            )

            built = build_reportpo_lifecycle_query(template, count=30000, restart_tokens=[["token-1"]])
            command = built["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]

            self.assertEqual(command["Query"]["From"], [{"Name": "p", "Entity": "PO", "Type": 0}])
            properties = [item["Column"]["Property"] for item in command["Query"]["Select"]]
            self.assertIn("EventID", properties)
            self.assertIn("OpDeviceID", properties)
            self.assertIn("IPdateTime", properties)
            self.assertIn("LastRestoDateTime", properties)
            self.assertEqual(
                command["Query"]["OrderBy"][0]["Expression"]["Column"]["Property"],
                "IPdateTime",
            )
            self.assertEqual(
                command["Binding"]["DataReduction"]["Primary"]["Window"]["Count"],
                30000,
            )
            self.assertEqual(
                command["Binding"]["DataReduction"]["Primary"]["Window"]["RestartTokens"],
                [["token-1"]],
            )

    def test_import_lifecycle_querydata_decodes_po_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "querydata.json"
            output = root / "lifecycle.csv"
            select = [
                _select("G0", "EventID"),
                _select("G1", "OpDeviceID"),
                _select("G2", "IPdateTime"),
                _select("G3", "LastRestoDateTime"),
                _select("G4", "CRdateTime"),
                _select("G5", "NotifyStatus"),
            ]
            schema = [
                {"N": "G0", "T": 1, "DN": "D0"},
                {"N": "G1", "T": 1, "DN": "D1"},
                {"N": "G2", "T": 7},
                {"N": "G3", "T": 7},
                {"N": "G4", "T": 7},
                {"N": "G5", "T": 4},
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
                                            "PH": [
                                                {
                                                    "DM0": [
                                                        {
                                                            "S": schema,
                                                            "C": [
                                                                0,
                                                                0,
                                                                _ms("2026-06-17T10:00:00"),
                                                                _ms("2026-06-17T10:45:00"),
                                                                _ms("2026-06-17T09:50:00"),
                                                                2,
                                                            ],
                                                        }
                                                    ]
                                                }
                                            ],
                                            "ValueDicts": {
                                                "D0": ["6847000001"],
                                                "D1": ["PFA01R-01"],
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

            result = import_reportpo_lifecycle(source, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["rows"], 1)
            self.assertEqual(result["with_ip_datetime"], 1)
            self.assertEqual(result["with_last_restore_datetime"], 1)
            self.assertEqual(rows[0]["event_number"], "6847000001")
            self.assertEqual(rows[0]["op_device_id"], "PFA01R-01")
            self.assertEqual(rows[0]["feeder"], "PFA01")
            self.assertEqual(rows[0]["lifecycle_quality"], "restore_available")

    def test_join_lifecycle_to_shadow_exact_device_exports_job_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, event_time="2026-06-17T10:03:00", device_id="PFA01R-01")
            lifecycle = root / "lifecycle.csv"
            _write_lifecycle(
                lifecycle,
                [
                    {
                        "event_number": "6847000001",
                        "op_device_id": "PFA01R-01",
                        "feeder": "PFA01",
                        "cr_datetime": "2026-06-17 09:50:00",
                        "ip_datetime": "2026-06-17 10:00:00",
                        "last_restore_datetime": "2026-06-17 10:45:00",
                        "cl_datetime": "2026-06-17 11:00:00",
                        "op_device_type": "recloser",
                        "group_device_type": "protection",
                        "voltage_level": "HV",
                        "notify_status": "2",
                        "notified": "Y",
                        "notify_in_time": "Y",
                        "lifecycle_quality": "restore_available",
                    }
                ],
            )
            output = root / "join.csv"

            result = join_reportpo_lifecycle_to_shadow(db.path, lifecycle, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["matched_rows"], 1)
            self.assertEqual(rows[0]["match_status"], "matched")
            self.assertEqual(rows[0]["match_reason"], "exact_device_time")
            self.assertEqual(rows[0]["event_number"], "6847000001")
            self.assertEqual(rows[0]["job_status_at_notification"], "in_progress")
            self.assertEqual(rows[0]["minutes_cr_to_ip"], "10.0")
            self.assertEqual(rows[0]["minutes_ip_to_restore"], "45.0")


def _select(name: str, property_name: str) -> dict:
    return {
        "Kind": 1,
        "Value": name,
        "GroupKeys": [
            {
                "Source": {"Entity": "PO", "Property": property_name},
                "Calc": name,
                "IsSameAsSelect": True,
            }
        ],
        "Name": f"PO.{property_name}",
    }


def _runtime_db_with_event(root: Path, event_time: str, device_id: str) -> RuntimeDb:
    db = RuntimeDb(root / "runtime.sqlite")
    db.init()
    db.insert_webex_message({"id": "msg-1", "roomId": "<REDACTED_ROOM_ID>", "created": event_time, "text": "event"})
    db.upsert_event(
        OutageEvent(
            event_id="event-1",
            source="webex",
            webex_message_id="msg-1",
            room_id="<REDACTED_ROOM_ID>",
            raw_text="event",
            event_time=event_time,
            outage_device=OutageDevice(device_type="Recloser", device_id=device_id, feeder=device_id[:5]),
        )
    )
    return db


def _write_lifecycle(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REPORTPO_LIFECYCLE_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in REPORTPO_LIFECYCLE_COLUMNS})


if __name__ == "__main__":
    unittest.main()
