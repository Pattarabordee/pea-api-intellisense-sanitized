import json
import unittest

from ais_etr.strict_relay_contract import validate_strict_pair, validate_strict_payload


def outage_payload() -> dict[str, str]:
    return {
        "request_id": "OUT-1",
        "source_event_id": "UPSTREAM-INCIDENT-1",
        "event_type": "OUTAGE",
        "meter_no": "REDACTED-METER-0000",
        "site_id": "REDACTED-SITE-0000",
        "timestamp": "2026-07-10T10:00:00+07:00",
        "outage_at": "2026-07-10T10:00:00+07:00",
    }


def restore_payload() -> dict[str, str]:
    return {
        **outage_payload(),
        "request_id": "RESTORE-1",
        "event_type": "RESTORE",
        "timestamp": "2026-07-10T10:30:00+07:00",
        "restore_at": "2026-07-10T10:30:00+07:00",
    }


class StrictRelayContractTests(unittest.TestCase):
    def test_valid_pair_preserves_upstream_correlation(self):
        result = validate_strict_pair(outage_payload(), restore_payload())
        self.assertTrue(result.valid)
        self.assertEqual(result.status, "STRICT_RELAY_READY")

    def test_source_and_site_are_optional_for_meter_state(self):
        result = validate_strict_payload({**outage_payload(), "source_event_id": ""})
        self.assertTrue(result.valid)
        without_site = {**outage_payload(), "site_id": "", "source_event_id": ""}
        self.assertTrue(validate_strict_payload(without_site).valid)

    def test_identity_mismatch_and_invalid_duration_are_rejected(self):
        mismatch = validate_strict_pair(outage_payload(), {**restore_payload(), "meter_no": "OTHER-METER"})
        self.assertIn("meter_identity_mismatch", mismatch.reason_codes)
        short = validate_strict_pair(outage_payload(), {**restore_payload(), "restore_at": "2026-07-10T10:05:00+07:00"})
        self.assertIn("duration_out_of_range", short.reason_codes)

    def test_naive_timestamp_requires_explicit_assumption(self):
        payload = {**outage_payload(), "timestamp": "2026-07-10T10:00:00", "outage_at": "2026-07-10T10:00:00"}
        rejected = validate_strict_payload(payload)
        self.assertIn("timestamp_timezone_offset_required", rejected.reason_codes)
        accepted = validate_strict_payload(payload, assume_bangkok_if_naive=True)
        self.assertTrue(accepted.valid)
        self.assertEqual(accepted.timezone_assumed_fields, ("outage_at", "timestamp"))

    def test_allowlisted_status_maps_but_cause_text_does_not(self):
        mapped = {**outage_payload(), "event_type": "", "power_status": "OFF"}
        self.assertTrue(validate_strict_payload(mapped).valid)
        cause_only = {**outage_payload(), "event_type": "", "main_cause": "power failure"}
        self.assertIn("event_type_required", validate_strict_payload(cause_only).reason_codes)

    def test_validation_output_never_contains_raw_identifiers(self):
        payload = outage_payload()
        safe = json.dumps(validate_strict_payload(payload).safe_dict(), ensure_ascii=False)
        self.assertNotIn(payload["meter_no"], safe)
        self.assertNotIn(payload["source_event_id"], safe)
        self.assertNotIn(payload["site_id"], safe)


if __name__ == "__main__":
    unittest.main()
