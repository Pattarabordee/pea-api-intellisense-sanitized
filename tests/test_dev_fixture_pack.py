import csv
import json
import tempfile
import unittest
from pathlib import Path

from ais_etr.ais_truth import import_ais_truth, match_ais_truth_to_shadow
from ais_etr.db import RuntimeDb
from ais_etr.matcher import ProtectionMatcher
from ais_etr.parser import parse_webex_message
from ais_etr.schemas import CustomerAsset, NotificationRecord
from ais_etr.utils import split_device_list


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "data" / "dev_fixtures"


class DevFixturePackTests(unittest.TestCase):
    def test_fixture_pack_runs_parser_matcher_and_ais_truth_smoke(self):
        messages = _read_jsonl(FIXTURE_ROOT / "webex_messages.jsonl")
        expected = _expected_by_message(FIXTURE_ROOT / "expected_shadow_results.csv")
        assets = _load_assets(FIXTURE_ROOT / "customer_assets.csv")
        matcher = ProtectionMatcher(assets)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = RuntimeDb(root / "dev_fixture_runtime.sqlite")
            db.init()
            db.upsert_customer_assets(assets)

            match_summary = {}
            for message in messages:
                event = parse_webex_message(message)
                self.assertIsNotNone(event, message["id"])
                assert event is not None
                result = matcher.match(event)
                match_summary[message["id"]] = result

                db.insert_webex_message(message)
                db.upsert_event(event)
                if result.matches:
                    db.insert_notification(
                        event.event_id,
                        "http://127.0.0.1:8080/api/v1/etr-notifications",
                        "shadow",
                        NotificationRecord(
                            payload={
                                "mode": "shadow",
                                "affected_customers": [
                                    {
                                        "customer": match.customer,
                                        "peano": match.peano,
                                        "feeder": match.feeder,
                                        "match_level": match.match_level,
                                    }
                                    for match in result.matches
                                ],
                            },
                            status="CAPTURED",
                            status_code=200,
                        ),
                    )

            canonical = root / "ais_truth_latest.csv"
            rejects = root / "ais_truth_rejects.csv"
            import_result = import_ais_truth(
                FIXTURE_ROOT / "ais_truth_source.csv",
                canonical,
                rejects,
            )
            self.assertEqual(import_result["valid_rows"], 4)
            self.assertEqual(import_result["review_rows"], 1)
            self.assertEqual(import_result["invalid_rows"], 0)

            mapping = root / "shadow_truth_mapping_ais.csv"
            audit = root / "ais_truth_shadow_match_audit.csv"
            match_result = match_ais_truth_to_shadow(db.path, canonical, mapping, audit)
            self.assertEqual(match_result["matched_rows"], 2)
            self.assertEqual(match_result["feeder_candidate_rows"], 1)

            audit_by_message = _csv_by_key(audit, "webex_message_id")
            for message_id, row in expected.items():
                event_match = match_summary[message_id]
                self.assertEqual(event_match.match_level or "", row["expected_match_level"])
                self.assertEqual(len(event_match.matches), int(row["expected_affected_count"]))
                self.assertNotIn("DEV_NO_METER", {match.peano for match in event_match.matches})

                audit_row = audit_by_message[message_id]
                self.assertEqual(audit_row["webex_device_id"], row["device_id"])
                self.assertEqual(audit_row["webex_feeder"], row["feeder"])
                self.assertEqual(audit_row["match_status"], row["expected_truth_match_status"])
                self.assertEqual(audit_row["match_level"], row["expected_truth_match_level"])
                self.assertEqual(audit_row["actual_restoration_minutes"], row["expected_actual_minutes"])

            mapping_by_message = _csv_by_key(mapping, "webex_message_id")
            self.assertEqual(mapping_by_message["dev-msg-001"]["actual_restoration_minutes"], "55.0")
            self.assertEqual(mapping_by_message["dev-msg-002"]["actual_restoration_minutes"], "120.0")
            self.assertEqual(mapping_by_message["dev-msg-003"]["actual_restoration_minutes"], "")
            self.assertEqual(mapping_by_message["dev-msg-004"]["actual_restoration_minutes"], "")

    def test_fixture_pack_has_no_real_secrets_or_raw_identifiers(self):
        forbidden = (
            "WEBEX_BOT_TOKEN",
            "WEBEX_ROOM_ID",
            "access_token",
            "refresh_token",
            "client_secret",
            "customer registration",
            "verbatim WebEx text",
        )
        for path in FIXTURE_ROOT.iterdir():
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for pattern in forbidden:
                    self.assertNotIn(pattern, text)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _expected_by_message(path: Path) -> dict[str, dict[str, str]]:
    return _csv_by_key(path, "message_id")


def _csv_by_key(path: Path, key: str) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row[key]: row for row in csv.DictReader(handle)}


def _load_assets(path: Path) -> list[CustomerAsset]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        CustomerAsset(
            peano=row["meter_ref"],
            customer=row["customer"],
            feeder=row["feeder"] or None,
            transformer_id=row["transformer_id"] or None,
            recloser_ids=split_device_list(row["recloser_ids"]),
            switch_ids=split_device_list(row["switch_ids"]),
            cb_ids=split_device_list(row["cb_ids"]),
            trace_status=row["trace_status"],
            confidence_eligible=row["confidence_eligible"].strip().upper() == "TRUE",
        )
        for row in rows
    ]


if __name__ == "__main__":
    unittest.main()
