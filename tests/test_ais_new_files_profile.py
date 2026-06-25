import csv
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from ais_etr.ais_new_files_profile import build_ais_new_files_profile


class AisNewFilesProfileTests(unittest.TestCase):
    def test_profile_builds_catalog_report_and_join_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            alarm_csv = root / "AC MAIN FAIL.csv"
            mapping_xlsx = root / "Meter_ID_NE For PEA_test_LatLong_R01 1.xlsx"
            legacy_xlsx = root / "NE_FAC_AC MAIN FAIL.xlsx"
            output_dir = root / "analysis"
            _write_alarm_csv(alarm_csv)
            _write_mapping_xlsx(mapping_xlsx)
            _write_minimal_xlsx(legacy_xlsx)

            result = build_ais_new_files_profile(alarm_csv, mapping_xlsx, legacy_xlsx, output_dir)

            self.assertEqual(result["alarm_rows"], 4)
            self.assertEqual(result["mapping_rows"], 3)
            self.assertEqual(result["mapping_rows_with_peano"], 3)
            self.assertEqual(result["truth_status"], "candidate_not_activated")
            self.assertEqual(result["phase1_sustained_candidate_rows"], 1)
            self.assertEqual(result["phase1_reject_rows"], 2)
            self.assertTrue(Path(result["catalog"]).exists())
            self.assertTrue(Path(result["report"]).exists())

            join_rows = _read_csv(Path(result["join_audit"]))
            site_join = next(row for row in join_rows if row["join_candidate"] == "sitecode_to_site_code")
            self.assertEqual(site_join["alarm_rows_matched"], "2")
            self.assertEqual(site_join["alarm_unique_keys_matched"], "1")
            self.assertEqual(site_join["mapping_duplicate_keys"], "1")

            alarm_profile = dict(_read_metric_csv(Path(result["alarm_profile"])))
            self.assertEqual(alarm_profile["missing_cleartime"], "1")
            self.assertEqual(alarm_profile["negative_duration_rows"], "1")
            self.assertEqual(alarm_profile["duration_band_>1_to_5_min"], "1")
            self.assertEqual(alarm_profile["duration_band_>5_to_60_min"], "1")

            report = Path(result["report"]).read_text(encoding="utf-8-sig")
            self.assertIn("Provisional Truth Logic", report)
            self.assertIn("Locked AIS Decisions", report)
            self.assertIn("Negative duration and `>24h` duration rows are rejected", report)
            self.assertIn("direct join is not strong enough", report)
            self.assertNotIn("PEANO_TEST_001", report)
            self.assertNotIn("TT_TEST_001", report)


def _write_alarm_csv(path: Path) -> None:
    rows = [
        {
            "Alertname": "ExtACMainFail",
            "Year of Firstoccurrence": "2026",
            "Alarmname": "AC MAIN FAIL-C1",
            "Firstoccurrence": "6/17/2026 10:00:00 AM",
            "Cleartime": "6/17/2026 10:30:00 AM",
            "Sitecode": "SITE_A",
            "Jobid": "",
            "Ticketid": "",
            "Severity": "Cleared",
            "Flappingcount": "0",
        },
        {
            "Alertname": "ExtACMainFail",
            "Year of Firstoccurrence": "2026",
            "Alarmname": "AC MAIN FAIL-C1",
            "Firstoccurrence": "6/17/2026 11:00:00 AM",
            "Cleartime": "6/17/2026 11:03:00 AM",
            "Sitecode": "SITE_B",
            "Jobid": "JB_TEST_001",
            "Ticketid": "TT_TEST_001",
            "Severity": "Cleared",
            "Flappingcount": "0",
        },
        {
            "Alertname": "ExtACMainFail",
            "Year of Firstoccurrence": "2026",
            "Alarmname": "AC MAIN FAIL-C2",
            "Firstoccurrence": "6/17/2026 12:00:00 PM",
            "Cleartime": "",
            "Sitecode": "SITE_C",
            "Jobid": "",
            "Ticketid": "",
            "Severity": "Major",
            "Flappingcount": "0",
        },
        {
            "Alertname": "ExtACMainFail",
            "Year of Firstoccurrence": "2026",
            "Alarmname": "AC MAIN FAIL-C1",
            "Firstoccurrence": "6/17/2026 01:00:00 PM",
            "Cleartime": "6/17/2026 12:55:00 PM",
            "Sitecode": "SITE_A",
            "Jobid": "",
            "Ticketid": "",
            "Severity": "Cleared",
            "Flappingcount": "0",
        },
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_mapping_xlsx(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Joined"
    headers = [
        "ID",
        "Region",
        "Meter",
        "CA_FORMAT",
        "Com",
        "Location ID",
        "Province",
        "Group",
        "PEA Meter",
        "CA",
        "Transformer PEANO",
        "KWH_JAN",
        "KWH_FEB",
        "KWH_MAR",
        "KWH_APR",
        "KWH_MAY",
        "KWH_JUN",
        "KWH_JUL",
        "KWH_AUG",
        "KWH_SEP",
        "KWH_OCT",
        "KWH_NOV",
        "KWH_DEC",
        "LAT",
        "LONG",
        "Remark",
        "SITE Code",
        "Companay",
    ]
    sheet.append(headers)
    sheet.append([1, "NE", "M1", "CA1", "FXL", "LOC1", "Sakon", "PEA", "PEANO_TEST_001", "CA1", "TX1", *([1] * 12), 17.1, 104.1, "", "SITE_A", "FXL"])
    sheet.append([2, "NE", "M2", "CA2", "AWN", "LOC2", "Sakon", "PEA", "PEANO_TEST_002", "CA2", "TX2", *([1] * 12), 17.2, 104.2, "", "SITE_A", "AWN"])
    sheet.append([3, "NE", "M3", "CA3", "FXL", "LOC3", "Sakon", "PEA", "PEANO_TEST_003", "CA3", "TX3", *([1] * 12), 17.3, 104.3, "", "", "FXL"])
    workbook.save(path)


def _write_minimal_xlsx(path: Path) -> None:
    workbook = Workbook()
    workbook.active["A1"] = "legacy"
    workbook.save(path)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_metric_csv(path: Path) -> list[tuple[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [(row["metric"], row["value"]) for row in csv.DictReader(handle)]


if __name__ == "__main__":
    unittest.main()
