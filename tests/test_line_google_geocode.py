import csv
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ais_etr.line_google_geocode import build_line_google_geocode_missing_places


class LineGoogleGeocodeTests(unittest.TestCase):
    def test_missing_api_key_writes_blocked_request_queue_without_raw_phone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _write_lookup(root)

            with patch.dict(os.environ, {}, clear=True):
                result = build_line_google_geocode_missing_places(
                    source=source,
                    output=root / "geocode.csv",
                    markdown_output=root / "geocode.md",
                    env_path=root / "missing.env",
                )

            self.assertEqual(result["status"], "blocked_missing_google_maps_api_key")
            rows = _read_csv(root / "geocode.csv")
            self.assertEqual(rows[0]["google_geocode_status"], "blocked_missing_google_maps_api_key")
            combined = (root / "geocode.csv").read_text(encoding="utf-8-sig") + (root / "geocode.md").read_text(encoding="utf-8")
            self.assertNotIn("093-324-8700", combined)
            self.assertIn("[PHONE_REDACTED]", combined)

    def test_fake_google_client_geocodes_first_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _write_lookup(root)
            client = FakeGeocodeClient()

            result = build_line_google_geocode_missing_places(
                source=source,
                output=root / "geocode.csv",
                markdown_output=root / "geocode.md",
                env_path=root / "missing.env",
                client=client,
            )

            self.assertEqual(result["status"], "ok")
            rows = _read_csv(root / "geocode.csv")
            self.assertEqual(rows[0]["google_geocode_status"], "geocoded")
            self.assertEqual(rows[0]["lat"], "17.1234567")
            self.assertEqual(rows[0]["lng"], "103.1234567")
            self.assertEqual(rows[0]["geocode_quality"], "high")
            self.assertIn("บ้านไฮหย่อง, Sakon Nakhon Thailand", client.queries)


class FakeGeocodeClient:
    def __init__(self):
        self.queries = []

    def geocode(self, query):
        self.queries.append(query)
        return {
            "status": "OK",
            "results": [
                {
                    "geometry": {
                        "location": {"lat": 17.1234567, "lng": 103.1234567},
                        "location_type": "ROOFTOP",
                    },
                    "place_id": "place-safe",
                    "formatted_address": "บ้านไฮหย่อง สกลนคร ประเทศไทย",
                    "types": ["premise"],
                }
            ],
        }


def _write_lookup(root: Path) -> Path:
    source = root / "lookup.csv"
    with source.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "message_ref",
                "lookup_status",
                "text_sanitized_excerpt",
                "place_queries",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "message_ref": "msg_missing",
                "lookup_status": "no_local_match",
                "text_sanitized_excerpt": "ไฟช็อตบ้านไฮหย่อง 093-324-8700",
                "place_queries": "บ้านไฮหย่อง; วัดบ้านไฮหย่อง",
            }
        )
    return source


def _read_csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    unittest.main()
