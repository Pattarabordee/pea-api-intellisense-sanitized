import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.ops_lifecycle import build_ops_lifecycle_template, validate_ops_lifecycle_file


class OpsLifecycleTests(unittest.TestCase):
    def test_template_prioritizes_refresh_residual_without_peano_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison = root / "comparison.csv"
            refresh = root / "long.csv"
            _write_comparison(comparison)
            _write_refresh(refresh)
            output = root / "template.csv"
            markdown = root / "template.md"

            result = build_ops_lifecycle_template(
                comparison,
                output,
                markdown,
                long_outage_csv=refresh,
                horizon_minutes=60,
                top_n=1,
            )
            rows = _read_csv(output)

            self.assertEqual(result["template_rows"], 1)
            self.assertEqual(rows[0]["event_id"], "event-b")
            self.assertEqual(rows[0]["priority_rank"], "1")
            self.assertEqual(rows[0]["source_system"], "eRespond")
            self.assertNotIn("6101", output.read_text(encoding="utf-8-sig"))
            self.assertIn("Fields To Fill", markdown.read_text(encoding="utf-8-sig"))

    def test_validate_rejects_missing_required_and_bad_time_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intake = root / "filled.csv"
            _write_intake(intake)
            valid = root / "valid.csv"
            rejects = root / "rejects.csv"
            markdown = root / "validation.md"

            result = validate_ops_lifecycle_file(intake, valid, rejects, markdown)
            reject_rows = _read_csv(rejects)

            self.assertEqual(result["rows"], 2)
            self.assertEqual(result["valid_rows"], 1)
            self.assertEqual(result["reject_rows"], 1)
            self.assertIn("first_restore_before_event_time", reject_rows[0]["validation_issues"])
            self.assertIn("missing_source_system", reject_rows[0]["validation_issues"])

    def test_template_prefers_webex_elapsed_residual_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            comparison = root / "comparison.csv"
            refresh = root / "long.csv"
            webex_elapsed = root / "webex.csv"
            _write_comparison(comparison)
            _write_refresh(refresh)
            _write_webex_elapsed(webex_elapsed)
            output = root / "template.csv"

            result = build_ops_lifecycle_template(
                comparison,
                output,
                long_outage_csv=refresh,
                webex_elapsed_csv=webex_elapsed,
                horizon_minutes=60,
                top_n=1,
            )
            rows = _read_csv(output)

            self.assertEqual(result["template_rows"], 1)
            self.assertEqual(rows[0]["event_id"], "event-a")
            self.assertEqual(rows[0]["webex_elapsed_refresh_error"], "500")


def _write_comparison(path: Path) -> None:
    columns = [
        "event_id",
        "incident_id",
        "event_time",
        "device_id",
        "feeder",
        "actual_restoration_minutes",
        "current_p50",
        "current_absolute_error",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "event_id": "event-a",
                "incident_id": "incident-a",
                "event_time": "2026-06-01T10:00:00",
                "device_id": "PFA01R-01",
                "feeder": "PFA01",
                "actual_restoration_minutes": "100",
                "current_p50": "40",
                "current_absolute_error": "60",
            }
        )
        writer.writerow(
            {
                "event_id": "event-b",
                "incident_id": "incident-b",
                "event_time": "2026-06-01T11:00:00",
                "device_id": "PFA02R-01",
                "feeder": "PFA02",
                "actual_restoration_minutes": "300",
                "current_p50": "30",
                "current_absolute_error": "270",
            }
        )


def _write_refresh(path: Path) -> None:
    columns = ["event_id", "horizon_minutes", "refresh_p50", "refresh_absolute_error"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow({"event_id": "event-a", "horizon_minutes": "60", "refresh_p50": "80", "refresh_absolute_error": "20"})
        writer.writerow({"event_id": "event-b", "horizon_minutes": "60", "refresh_p50": "60", "refresh_absolute_error": "240"})


def _write_webex_elapsed(path: Path) -> None:
    columns = ["event_id", "refresh_p50", "refresh_absolute_error"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow({"event_id": "event-a", "refresh_p50": "600", "refresh_absolute_error": "500"})
        writer.writerow({"event_id": "event-b", "refresh_p50": "295", "refresh_absolute_error": "5"})


def _write_intake(path: Path) -> None:
    columns = [
        "event_id",
        "event_time",
        "source_system",
        "outage_reported_time",
        "first_restore_time",
        "crew_dispatched_time",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow(
            {
                "event_id": "event-ok",
                "event_time": "2026-06-01 10:00:00",
                "source_system": "eRespond",
                "outage_reported_time": "2026-06-01 10:00:00",
                "crew_dispatched_time": "2026-06-01 10:15:00",
                "first_restore_time": "2026-06-01 11:00:00",
            }
        )
        writer.writerow(
            {
                "event_id": "event-bad",
                "event_time": "2026-06-01 10:00:00",
                "source_system": "",
                "outage_reported_time": "2026-06-01 10:00:00",
                "crew_dispatched_time": "2026-06-01 10:15:00",
                "first_restore_time": "2026-06-01 09:59:00",
            }
        )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
