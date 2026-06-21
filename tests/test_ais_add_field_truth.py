import csv
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from ais_etr.ais_add_field_truth import import_ais_add_field_truth


class AisAddFieldTruthTests(unittest.TestCase):
    def test_import_add_field_truth_joins_location_id_and_splits_quality(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mapping = root / "mapping.csv"
            mapping.write_text(
                "\n".join(
                    [
                        "Location ID,Meter,หมายเลขเครื่องวัด PEA,SITE Code",
                        "LOC1,WRONG_GENERIC_METER,PEA001,SITEA",
                        "LOC2,WRONG_GENERIC_METER,,SITEB",
                        "LOC3,WRONG_GENERIC_METER,PEA003,SITEC",
                        "LOC3,WRONG_GENERIC_METER,PEA004,SITEC",
                        "LOC4,WRONG_GENERIC_METER,PEA005,SITED",
                    ]
                ),
                encoding="utf-8-sig",
            )
            source = root / "alarm.csv"
            source.write_text(
                "\n".join(
                    [
                        "Location ID,Sitecode,Firstoccurrence,Cleartime,Alarmname",
                        "LOC1,SITEA,6/17/2026 10:00:00 AM,6/17/2026 10:40:00 AM,AC MAIN FAIL-C1",
                        "LOC1,SITEA,6/17/2026 11:00:00 AM,6/17/2026 11:03:00 AM,AC MAIN FAIL-C1",
                        "LOC2,SITEB,6/17/2026 12:00:00 PM,6/17/2026 12:40:00 PM,AC MAIN FAIL-C1",
                        "LOC3,SITEC,6/17/2026 01:00:00 PM,6/17/2026 01:40:00 PM,AC MAIN FAIL-C1",
                        "LOC4,SITED,6/17/2026 02:00:00 PM,6/17/2026 01:59:00 PM,AC MAIN FAIL-C1",
                    ]
                ),
                encoding="utf-8-sig",
            )
            output = root / "candidate.csv"
            review = root / "review.csv"
            rejects = root / "rejects.csv"
            audit = root / "audit.csv"

            result = import_ais_add_field_truth(
                source,
                mapping,
                output,
                review,
                rejects,
                audit,
                report_markdown=None,
            )

            self.assertEqual(result["rows"], 5)
            self.assertEqual(result["ok_rows"], 1)
            self.assertEqual(result["review_rows"], 1)
            self.assertEqual(result["reject_rows"], 3)
            self.assertEqual(result["quality_counts"]["OK"], 1)
            self.assertEqual(result["quality_counts"]["REVIEW_SHORT"], 1)
            self.assertEqual(result["quality_counts"]["MISSING_PEANO_MAPPING"], 1)
            self.assertEqual(result["quality_counts"]["AMBIGUOUS_PEANO_MAPPING"], 1)
            self.assertEqual(result["quality_counts"]["INVALID_NEGATIVE"], 1)

            rows = _read_csv(output)
            self.assertEqual(rows[0]["peano"], "PEA001")
            self.assertNotEqual(rows[0]["peano"], "WRONG_GENERIC_METER")
            self.assertEqual(rows[0]["actual_restoration_minutes"], "40.0")
            self.assertEqual(rows[0]["truth_target"], "ais_site_actual_restoration_minutes")
            self.assertEqual(rows[0]["truth_definition"], "AIS_POWER_RESTORE_TIME - AIS_POWER_OUTAGE_TIME")
            self.assertEqual(rows[1]["truth_quality"], "REVIEW_SHORT")

            review_rows = _read_csv(review)
            reject_rows = _read_csv(rejects)
            self.assertEqual(len(review_rows), 1)
            self.assertEqual(len(reject_rows), 3)

    def test_import_add_field_truth_reads_xlsx_and_truncates_audit_alarm_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mapping = root / "mapping.xlsx"
            map_wb = Workbook()
            map_ws = map_wb.active
            map_ws.title = "Joined"
            map_ws.append(["Location ID", "หมายเลขเครื่องวัด PEA", "SITE Code"])
            map_ws.append(["1001", "PEA1001", "SITE1001"])
            map_wb.save(mapping)

            source = root / "alarm.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.title = "AC MAIN FAIL"
            ws.append(["Location ID", "Sitecode", "Firstoccurrence", "Cleartime", "Description"])
            ws.append(
                [
                    "1001",
                    "SITE1001",
                    "6/17/2026 10:00:00 AM",
                    "6/17/2026 10:10:00 AM",
                    "AC MAIN FAIL-C1 " + ("very long raw description " * 20),
                ]
            )
            wb.save(source)

            output = root / "candidate.csv"
            audit = root / "audit.csv"

            result = import_ais_add_field_truth(
                source,
                mapping,
                output,
                root / "review.csv",
                root / "rejects.csv",
                audit,
                report_markdown=None,
            )

            self.assertEqual(result["ok_rows"], 1)
            audit_text = audit.read_text(encoding="utf-8-sig")
            self.assertIn("AC MAIN FAIL-C1", audit_text)
            self.assertNotIn("very long raw description " * 5, audit_text)

    def test_import_add_field_truth_reads_ais_create_done_schema_and_cause_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mapping = root / "mapping.csv"
            mapping.write_text(
                "\n".join(
                    [
                        "Location ID,PEANO,SITE Code",
                        "771028,PEA771028,BPAGM",
                    ]
                ),
                encoding="utf-8-sig",
            )
            source = root / "alarm.csv"
            source.write_text(
                "\n".join(
                    [
                        "MAINCAUSE,SUBCAUSE2,JB_ID,SiteCode,SUBCAUSE1,CREATE_DATE,DONE_DATE,Down Time,Location ID",
                        "Fault : Facility - Principle Node,MEA/PEA Activity.,JB26-0073950,BPAGM,AC Main Failed,1/13/2026 11:36:57 PM,1/14/2026 1:03:29 AM,87,771028",
                    ]
                ),
                encoding="utf-8-sig",
            )
            output = root / "candidate.csv"
            audit = root / "audit.csv"

            result = import_ais_add_field_truth(
                source,
                mapping,
                output,
                root / "review.csv",
                root / "rejects.csv",
                audit,
                report_markdown=root / "report.md",
            )

            self.assertEqual(result["ok_rows"], 1)
            self.assertEqual(result["cause_counts"]["pea_activity"], 1)
            self.assertEqual(result["duration_consistency_counts"]["matches_within_1_minute"], 1)

            rows = _read_csv(output)
            self.assertEqual(rows[0]["outage_start_time"], "2026-01-13 23:36:57")
            self.assertEqual(rows[0]["power_restore_time"], "2026-01-14 01:03:29")
            self.assertEqual(rows[0]["actual_restoration_minutes"], "86.53")
            self.assertIn("cause_category=pea_activity", rows[0]["truth_notes"])
            self.assertIn("job_id=JB26-0073950", rows[0]["truth_notes"])

            audit_rows = _read_csv(audit)
            self.assertEqual(audit_rows[0]["cause_category"], "pea_activity")
            self.assertEqual(audit_rows[0]["duration_consistency"], "matches_within_1_minute")

    def test_import_add_field_truth_classifies_pea_backup_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mapping = root / "mapping.csv"
            mapping.write_text(
                "\n".join(
                    [
                        "Location ID,PEANO,SITE Code",
                        "771029,PEA771029,BPAGM",
                    ]
                ),
                encoding="utf-8-sig",
            )
            source = root / "alarm.csv"
            source.write_text(
                "\n".join(
                    [
                        "MAINCAUSE,SUBCAUSE2,JB_ID,SiteCode,CREATE_DATE,DONE_DATE,Down Time,Location ID",
                        "Fault : Facility - Base Station,AC- MEA/PEA (have backup system),JB26-0073951,BPAGM,1/13/2026 11:36:00 PM,1/14/2026 1:03:00 AM,87,771029",
                    ]
                ),
                encoding="utf-8-sig",
            )

            result = import_ais_add_field_truth(
                source,
                mapping,
                root / "candidate.csv",
                root / "review.csv",
                root / "rejects.csv",
                root / "audit.csv",
                report_markdown=None,
            )

            self.assertEqual(result["ok_rows"], 1)
            self.assertEqual(result["cause_counts"]["pea_have_backup"], 1)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
