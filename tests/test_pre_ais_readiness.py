import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ais_etr.pre_ais_readiness import (
    KIT_README_NAME,
    KIT_SAMPLE_NAME,
    KIT_TEMPLATE_NAME,
    build_ais_truth_intake_kit,
    build_pre_ais_evidence_pack,
    run_ais_truth_dry_run,
)


class PreAisReadinessTests(unittest.TestCase):
    def test_intake_kit_writes_template_readme_and_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            result = build_ais_truth_intake_kit(root)

            self.assertEqual(result["sample_rows"], 5)
            self.assertTrue((root / KIT_TEMPLATE_NAME).exists())
            self.assertTrue((root / KIT_SAMPLE_NAME).exists())
            self.assertTrue((root / KIT_README_NAME).exists())
            with (root / KIT_TEMPLATE_NAME).open(encoding="utf-8-sig", newline="") as handle:
                template_rows = list(csv.DictReader(handle))
                self.assertEqual(
                    handle.seek(0) or handle.readline().strip().split(",")[:4],
                    ["site_id", "peano", "outage_start_time", "power_restore_time"],
                )
            self.assertEqual(template_rows, [])
            readme = (root / KIT_README_NAME).read_text(encoding="utf-8-sig")
            self.assertIn("power_restore_time - outage_start_time", readme)
            self.assertIn(">5", readme)

    def test_dry_run_validates_sample_and_tests_synthetic_shadow_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_ais_truth_intake_kit(root)

            result = run_ais_truth_dry_run(root / KIT_SAMPLE_NAME, root)

            self.assertEqual(result["accuracy_claim"], "not_claimed_sample_data_only")
            self.assertEqual(result["import"]["valid_rows"], 1)
            self.assertEqual(result["import"]["review_rows"], 1)
            self.assertEqual(result["import"]["invalid_rows"], 3)
            self.assertEqual(result["match"]["matched_rows"], 1)
            self.assertEqual(result["match"]["filled_rows"], 1)
            mapping = root / "private" / "dry_run_shadow_truth_mapping_sample.csv"
            self.assertTrue(mapping.exists())
            self.assertIn("dry-run-webex-message-001", mapping.read_text(encoding="utf-8-sig"))

    def test_pre_ais_evidence_pack_summarizes_without_sample_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            intake = root / "intake"
            build_ais_truth_intake_kit(intake)
            db_path = _small_runtime_db(root)
            truth_quality = root / "truth_quality.csv"
            model_compare = root / "model_compare.csv"
            no_match = root / "no_match.csv"
            station_review = root / "station_review.csv"
            output = root / "pack.md"
            _write_truth_quality(truth_quality)
            _write_model_compare(model_compare)
            _write_no_match(no_match)
            _write_station_review(station_review)

            result = build_pre_ais_evidence_pack(
                output,
                intake_dir=intake,
                db_path=db_path,
                truth_quality_audit=truth_quality,
                shadow_model_comparison=model_compare,
                no_match_candidates=no_match,
                station_mapping_review=station_review,
            )

            text = output.read_text(encoding="utf-8-sig")
            self.assertEqual(result["truth_summary"]["sustained_rows"], 1)
            self.assertIn("Sustained truth rows | 1 | >= 30 | insufficient", text)
            self.assertIn("PFA04VB-01 (14 events)", text)
            self.assertNotIn("PEANO_PLACEHOLDER_001", text)
            self.assertNotIn("Dry-run outage", text)


def _small_runtime_db(root: Path) -> Path:
    db_path = root / "runtime.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE webex_messages (id TEXT);
            CREATE TABLE outage_events (event_id TEXT);
            CREATE TABLE predictions (id INTEGER);
            CREATE TABLE notifications (id INTEGER);
            CREATE TABLE customer_assets (peano TEXT);
            INSERT INTO webex_messages VALUES ('m1');
            INSERT INTO outage_events VALUES ('e1');
            INSERT INTO predictions VALUES (1);
            INSERT INTO notifications VALUES (1);
            INSERT INTO customer_assets VALUES ('PEANO_TEST_PRIVATE');
            """
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _write_truth_quality(path: Path) -> None:
    columns = [
        "evaluation_policy",
        "actual_restoration_minutes",
        "current_absolute_error",
        "current_covered_q10_q90",
    ]
    rows = [
        {
            "evaluation_policy": "sustained_outage_eligible",
            "actual_restoration_minutes": "30",
            "current_absolute_error": "12",
            "current_covered_q10_q90": "TRUE",
        },
        {
            "evaluation_policy": "momentary_micro_review",
            "actual_restoration_minutes": "0.5",
            "current_absolute_error": "40",
            "current_covered_q10_q90": "FALSE",
        },
    ]
    _write_csv(path, columns, rows)


def _write_model_compare(path: Path) -> None:
    columns = ["actual_restoration_minutes", "current_absolute_error", "challenger_absolute_error"]
    rows = [
        {
            "actual_restoration_minutes": "30",
            "current_absolute_error": "12",
            "challenger_absolute_error": "10",
        }
    ]
    _write_csv(path, columns, rows)


def _write_no_match(path: Path) -> None:
    columns = ["device_id", "event_count"]
    rows = [{"device_id": "PFA04VB-01", "event_count": "14"}]
    _write_csv(path, columns, rows)


def _write_station_review(path: Path) -> None:
    columns = ["station_prefix", "scope", "status"]
    rows = [{"station_prefix": "PFA", "scope": "pilot_3", "status": "approved"}]
    _write_csv(path, columns, rows)


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
