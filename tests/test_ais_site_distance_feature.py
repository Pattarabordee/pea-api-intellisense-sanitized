import csv
import tempfile
import unittest
from pathlib import Path

from ais_etr.ais_site_distance_feature import build_ais_site_distance_features


class AisSiteDistanceFeatureTests(unittest.TestCase):
    def test_enriches_ais_truth_rows_and_drops_sensitive_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "ais_truth.csv"
            distance = root / "distances.csv"
            output = root / "features.csv"
            markdown = root / "features.md"
            _write_csv(
                source,
                [
                    "site_id",
                    "peano",
                    "outage_start_time",
                    "power_restore_time",
                    "actual_restoration_minutes",
                    "feeder",
                    "truth_notes",
                ],
                [
                    {
                        "site_id": "881209",
                        "peano": "610123456789",
                        "outage_start_time": "2026-06-17 10:00:00",
                        "power_restore_time": "2026-06-17 10:45:00",
                        "actual_restoration_minutes": "45",
                        "feeder": "PFA01",
                        "truth_notes": "owner note",
                    }
                ],
            )
            _write_csv(
                distance,
                [
                    "site_ref",
                    "nearest_pea_office",
                    "nearest_office_size",
                    "road_distance_km",
                    "straight_line_km",
                    "osrm_duration_min",
                    "route_status",
                ],
                [
                    {
                        "site_ref": "881209",
                        "nearest_pea_office": "กฟส.กันทรารมย์ (M)",
                        "nearest_office_size": "M",
                        "road_distance_km": "28.273",
                        "straight_line_km": "21.878",
                        "osrm_duration_min": "31",
                        "route_status": "ok",
                    }
                ],
            )

            result = build_ais_site_distance_features(source, distance, output, markdown)
            rows = _read_csv(output)
            header = output.read_text(encoding="utf-8-sig").splitlines()[0]

            self.assertEqual(result["matched_rows"], 1)
            self.assertEqual(result["no_distance_match_rows"], 0)
            self.assertNotIn("peano", header)
            self.assertNotIn("truth_notes", header)
            self.assertEqual(rows[0]["nearest_pea_office_road_distance_km"], "28.273")
            self.assertEqual(rows[0]["nearest_pea_office_round_trip_km"], "56.546")
            self.assertEqual(rows[0]["nearest_pea_office_round_trip_band"], "51-100")
            self.assertEqual(rows[0]["nearest_pea_office_oneway_over_25km"], "true")
            self.assertIn("AIS Site Distance Feature", markdown.read_text(encoding="utf-8-sig"))

    def test_uses_location_id_alias_and_reports_missing_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.csv"
            distance = root / "distance.csv"
            output = root / "output.csv"
            _write_csv(
                source,
                ["Location ID", "actual_restoration_minutes"],
                [
                    {"Location ID": "1001.0", "actual_restoration_minutes": "30"},
                    {"Location ID": "", "actual_restoration_minutes": "45"},
                    {"Location ID": "9999", "actual_restoration_minutes": "60"},
                ],
            )
            _write_csv(
                distance,
                ["site_ref", "nearest_pea_office", "road_distance_km", "route_status"],
                [{"site_ref": "1001", "nearest_pea_office": "กฟจ.ทดสอบ", "road_distance_km": "10", "route_status": "ok"}],
            )

            result = build_ais_site_distance_features(source, distance, output)
            rows = _read_csv(output)

            self.assertEqual(result["site_id_column"], "Location ID")
            self.assertEqual(result["matched_rows"], 1)
            self.assertEqual(result["missing_site_id_rows"], 1)
            self.assertEqual(result["no_distance_match_rows"], 1)
            self.assertEqual(rows[0]["nearest_pea_office_round_trip_band"], "0-50")
            self.assertEqual(rows[1]["nearest_pea_office_feature_status"], "missing_site_id")
            self.assertEqual(rows[2]["nearest_pea_office_feature_status"], "no_distance_match")

    def test_duplicate_site_refs_pick_shortest_distance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.csv"
            distance = root / "distance.csv"
            output = root / "output.csv"
            _write_csv(source, ["site_id"], [{"site_id": "AIS001"}])
            _write_csv(
                distance,
                ["site_ref", "nearest_pea_office", "road_distance_km", "route_status"],
                [
                    {"site_ref": "AIS001__coord1", "nearest_pea_office": "กฟจ.A", "road_distance_km": "50", "route_status": "ok"},
                    {"site_ref": "AIS001__coord2", "nearest_pea_office": "กฟจ.B", "road_distance_km": "12", "route_status": "ok"},
                ],
            )

            result = build_ais_site_distance_features(source, distance, output)
            rows = _read_csv(output)

            self.assertEqual(result["matched_rows"], 1)
            self.assertEqual(rows[0]["nearest_pea_office_name"], "กฟจ.B")
            self.assertEqual(rows[0]["nearest_pea_office_road_distance_km"], "12")
            self.assertEqual(rows[0]["nearest_pea_office_feature_status"], "matched_duplicate_site_ref_min_distance")

    def test_missing_distance_file_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.csv"
            _write_csv(source, ["site_id"], [{"site_id": "AIS001"}])

            with self.assertRaises(FileNotFoundError):
                build_ais_site_distance_features(source, root / "missing.csv", root / "output.csv")


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


if __name__ == "__main__":
    unittest.main()
