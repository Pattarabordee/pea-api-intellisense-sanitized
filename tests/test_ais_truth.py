import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.ais_truth import import_ais_truth, match_ais_truth_to_shadow, write_ais_truth_template
from ais_etr.db import RuntimeDb
from ais_etr.schemas import NotificationRecord, OutageDevice, OutageEvent


class AisTruthTests(unittest.TestCase):
    def test_template_writes_expected_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "ais_truth_template.csv"

            result = write_ais_truth_template(output, include_example=True)
            text = output.read_text(encoding="utf-8-sig")

            self.assertEqual(result["status"], "created")
            self.assertIn("site_id,peano,outage_start_time,power_restore_time", text)
            self.assertIn("AIS_SITE_001", text)

    def test_import_ais_truth_computes_duration_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ais_truth.csv"
            source.write_text(
                "\n".join(
                    [
                        "site_id,peano,outage_start_time,power_restore_time,event_number,device_id,feeder,source,notes",
                        "AIS001,6101,2026-06-17 10:00:00,2026-06-17 10:45:00,6847000001,PFA01R-01,PFA01,AIS,confirmed",
                    ]
                ),
                encoding="utf-8-sig",
            )
            output = root / "canonical.csv"
            rejects = root / "rejects.csv"

            result = import_ais_truth(source, output, rejects)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["rows"], 1)
            self.assertEqual(result["valid_rows"], 1)
            self.assertEqual(result["invalid_rows"], 0)
            self.assertEqual(rows[0]["actual_restoration_minutes"], "45.0")
            self.assertEqual(rows[0]["truth_source"], "ais_site_power_status")
            self.assertEqual(rows[0]["truth_target"], "ais_site_actual_restoration_minutes")
            self.assertEqual(rows[0]["truth_definition"], "AIS_POWER_RESTORE_TIME - AIS_POWER_OUTAGE_TIME")
            self.assertEqual(rows[0]["truth_quality"], "OK")

    def test_import_ais_truth_flags_invalid_and_review_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ais_truth.csv"
            source.write_text(
                "\n".join(
                    [
                        "site_id,peano,outage_start_time,power_restore_time",
                        "AIS001,6101,2026-06-17 10:00:00,2026-06-17 10:02:00",
                        "AIS002,6102,2026-06-17 10:00:00,2026-06-17 09:59:00",
                        ",,2026-06-17 10:00:00,2026-06-17 10:30:00",
                        "AIS003,6103,2026-06-17 10:00:00,",
                    ]
                ),
                encoding="utf-8-sig",
            )
            output = root / "canonical.csv"
            rejects = root / "rejects.csv"

            result = import_ais_truth(source, output, rejects)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            with rejects.open(encoding="utf-8-sig", newline="") as handle:
                reject_rows = list(csv.DictReader(handle))

            self.assertEqual(result["review_rows"], 1)
            self.assertEqual(result["invalid_rows"], 3)
            self.assertEqual(rows[0]["truth_quality"], "REVIEW_SHORT")
            self.assertEqual(rows[1]["truth_quality"], "INVALID_NEGATIVE")
            self.assertEqual(rows[2]["truth_quality"], "MISSING_ASSET_ID")
            self.assertEqual(rows[3]["truth_quality"], "MISSING_RESTORE")
            self.assertEqual(len(reject_rows), 3)

    def test_import_ais_truth_accepts_common_header_aliases_and_buddhist_year(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ais_truth.csv"
            source.write_text(
                "\n".join(
                    [
                        "site,pea_no,down_time,up_time,event_id",
                        "AIS001,6101,17/06/2569 10:00,17/06/2569 10:45,6847000001",
                    ]
                ),
                encoding="utf-8-sig",
            )
            output = root / "canonical.csv"

            result = import_ais_truth(source, output)
            with output.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["valid_rows"], 1)
            self.assertEqual(result["mapped_columns"]["outage_start_time"], "down_time")
            self.assertEqual(rows[0]["outage_start_time"], "2026-06-17 10:00:00")
            self.assertEqual(rows[0]["actual_restoration_minutes"], "45.0")

    def test_match_ais_truth_by_event_number_fills_shadow_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, parsed_event_number="6847000001")
            ais_truth = root / "ais_truth.csv"
            _write_ais_truth(
                ais_truth,
                [
                    {
                        "site_id": "AIS001",
                        "peano": "6101",
                        "outage_start_time": "2026-06-17 10:00:00",
                        "power_restore_time": "2026-06-17 10:45:00",
                        "actual_restoration_minutes": "45.0",
                        "event_number": "6847000001",
                        "truth_quality": "OK",
                    }
                ],
            )
            mapping = root / "shadow_truth_mapping_ais.csv"
            audit = root / "audit.csv"

            result = match_ais_truth_to_shadow(db.path, ais_truth, mapping, audit)
            with mapping.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            with audit.open(encoding="utf-8-sig", newline="") as handle:
                audit_rows = list(csv.DictReader(handle))

            self.assertEqual(result["matched_rows"], 1)
            self.assertEqual(result["filled_rows"], 1)
            self.assertEqual(rows[0]["event_number"], "6847000001")
            self.assertEqual(rows[0]["actual_restoration_minutes"], "45.0")
            self.assertEqual(rows[0]["truth_source"], "ais_site_power_status")
            self.assertEqual(rows[0]["truth_target"], "ais_site_actual_restoration_minutes")
            self.assertEqual(audit_rows[0]["match_level"], "event_number")

    def test_match_ais_truth_by_affected_peano_aggregates_max(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, affected_peanos=("6101", "6102"))
            ais_truth = root / "ais_truth.csv"
            _write_ais_truth(
                ais_truth,
                [
                    {
                        "site_id": "AIS001",
                        "peano": "6101",
                        "outage_start_time": "2026-06-17 10:01:00",
                        "power_restore_time": "2026-06-17 10:31:00",
                        "actual_restoration_minutes": "30.0",
                        "truth_quality": "OK",
                    },
                    {
                        "site_id": "AIS002",
                        "peano": "6102",
                        "outage_start_time": "2026-06-17 10:01:00",
                        "power_restore_time": "2026-06-17 10:46:00",
                        "actual_restoration_minutes": "45.0",
                        "truth_quality": "OK",
                    },
                ],
            )
            mapping = root / "shadow_truth_mapping_ais.csv"

            result = match_ais_truth_to_shadow(db.path, ais_truth, mapping)
            with mapping.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(result["matched_rows"], 1)
            self.assertEqual(rows[0]["actual_restoration_minutes"], "45.0")
            self.assertIn("affected_peano_time", rows[0]["truth_notes"])
            self.assertIn("ais_rows=2", rows[0]["truth_notes"])

    def test_match_ais_truth_feeder_candidate_is_audit_only_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = _runtime_db_with_event(root, device_id="PFA01R-01", feeder="PFA01")
            ais_truth = root / "ais_truth.csv"
            _write_ais_truth(
                ais_truth,
                [
                    {
                        "site_id": "AIS001",
                        "peano": "6101",
                        "outage_start_time": "2026-06-17 10:01:00",
                        "power_restore_time": "2026-06-17 10:46:00",
                        "actual_restoration_minutes": "45.0",
                        "feeder": "PFA01",
                        "truth_quality": "OK",
                    }
                ],
            )
            mapping = root / "shadow_truth_mapping_ais.csv"
            audit = root / "audit.csv"

            result = match_ais_truth_to_shadow(db.path, ais_truth, mapping, audit)
            with mapping.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            with audit.open(encoding="utf-8-sig", newline="") as handle:
                audit_rows = list(csv.DictReader(handle))

            self.assertEqual(result["filled_rows"], 0)
            self.assertEqual(result["feeder_candidate_rows"], 1)
            self.assertEqual(rows[0]["actual_restoration_minutes"], "")
            self.assertEqual(audit_rows[0]["match_status"], "feeder_candidate_only")

def _runtime_db_with_event(
    root: Path,
    event_time: str = "2026-06-17T10:00:00Z",
    device_id: str = "PFA01R-01",
    feeder: str = "PFA01",
    parsed_event_number: str | None = None,
    affected_peanos: tuple[str, ...] = (),
) -> RuntimeDb:
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
            outage_device=OutageDevice(device_type="Recloser", device_id=device_id, feeder=feeder),
            parsed_fields={"event_number": parsed_event_number},
        )
    )
    if affected_peanos:
        db.insert_notification(
            "event-1",
            "http://127.0.0.1:8080/api/v1/etr-notifications",
            "shadow",
            NotificationRecord(
                payload={
                    "mode": "shadow",
                    "affected_customers": [
                        {"customer": "AIS", "peano": peano, "feeder": feeder, "match_level": "recloser"}
                        for peano in affected_peanos
                    ],
                },
                status="SENT",
                status_code=200,
            ),
        )
    return db


def _write_ais_truth(path: Path, rows: list[dict[str, str]]) -> None:
    columns = [
        "site_id",
        "peano",
        "outage_start_time",
        "power_restore_time",
        "actual_restoration_minutes",
        "event_number",
        "device_id",
        "feeder",
        "source",
        "truth_source",
        "truth_target",
        "truth_definition",
        "truth_quality",
        "truth_notes",
        "source_file",
        "source_row_number",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for index, row in enumerate(rows, start=2):
            defaults = {
                "source": "AIS",
                "truth_source": "ais_site_power_status",
                "truth_target": "ais_site_actual_restoration_minutes",
                "truth_definition": "AIS_POWER_RESTORE_TIME - AIS_POWER_OUTAGE_TIME",
                "source_file": str(path),
                "source_row_number": str(index),
            }
            writer.writerow({column: {**defaults, **row}.get(column, "") for column in columns})


if __name__ == "__main__":
    unittest.main()
