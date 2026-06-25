import csv
import tempfile
import unittest
from pathlib import Path

from tools.build_failed_site_nearest_ne_pea_road_distance import (
    Office,
    Site,
    _best_from_matrix_row,
    _choose_better,
    load_failed_site_ids,
    load_offices,
)


class FailedSiteNearestNePeaRoadDistanceTests(unittest.TestCase):
    def test_load_failed_site_ids_normalizes_location_id_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "failed.csv"
            _write_csv(
                source,
                ["Location ID", "actual_restoration_minutes"],
                [
                    {"Location ID": "1001.0", "actual_restoration_minutes": "30"},
                    {"Location ID": " 1002 ", "actual_restoration_minutes": "45"},
                    {"Location ID": "", "actual_restoration_minutes": "60"},
                ],
            )

            site_ids, rows = load_failed_site_ids(source)

            self.assertEqual(rows, 3)
            self.assertEqual(site_ids, {"1001", "1002"})

    def test_load_offices_skips_invalid_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            offices = root / "offices.csv"
            _write_csv(
                offices,
                ["office_id", "office_name", "office_type", "official_address", "lat", "lon", "coordinate_source", "coordinate_url", "confidence"],
                [
                    {
                        "office_id": "ne_pea_001",
                        "office_name": "PEA A",
                        "office_type": "provincial",
                        "official_address": "addr",
                        "lat": "17.1",
                        "lon": "102.1",
                        "coordinate_source": "longdo",
                        "coordinate_url": "https://example.invalid/a",
                        "confidence": "high",
                    },
                    {
                        "office_id": "bad",
                        "office_name": "PEA Bad",
                        "office_type": "branch",
                        "official_address": "addr",
                        "lat": "",
                        "lon": "102.1",
                        "coordinate_source": "",
                        "coordinate_url": "",
                        "confidence": "low",
                    },
                ],
            )

            rows = load_offices(offices)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].office_id, "ne_pea_001")
            self.assertEqual(rows[0].office_type, "provincial")

    def test_best_from_matrix_row_uses_shortest_road_distance(self):
        site = Site("site-a", "site-a", "", "AIS", "province", 17.0, 102.0)
        offices = [
            Office("office-a", "PEA A", "branch", "", 17.1, 102.0, "longdo", "", "high"),
            Office("office-b", "PEA B", "branch", "", 17.2, 102.0, "longdo", "", "high"),
        ]

        best = _best_from_matrix_row(site, offices, [30000.0, 12000.0], [1800.0, 720.0])

        self.assertIsNotNone(best)
        self.assertEqual(best["nearest_office_id"], "office-b")
        self.assertEqual(best["road_distance_km"], 12.0)
        self.assertEqual(best["osrm_duration_min"], 12.0)
        self.assertEqual(best["route_status"], "ok")

    def test_choose_better_keeps_shorter_candidate(self):
        current = {"nearest_office_id": "a", "road_distance_km": 20.0}
        longer = {"nearest_office_id": "b", "road_distance_km": 25.0}
        shorter = {"nearest_office_id": "c", "road_distance_km": 10.0}

        self.assertEqual(_choose_better(current, longer), current)
        self.assertEqual(_choose_better(current, shorter), shorter)
        self.assertEqual(_choose_better(None, shorter), shorter)


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
