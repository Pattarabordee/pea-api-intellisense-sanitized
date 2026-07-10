"""Validate PEA relay payloads for the strict prospective AIS truth contract."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any


MAX_REQUEST_ID = 128
MAX_METER = 64
MAX_SOURCE_EVENT_ID = 128
MAX_SITE_ID = 128
MIN_DURATION_MINUTES = 5.0
MAX_DURATION_MINUTES = 1440.0


@dataclass(frozen=True)
class RelayValidation:
    status: str
    reason_codes: tuple[str, ...]
    timezone_assumed_fields: tuple[str, ...]
    payload_ref: str

    @property
    def valid(self) -> bool:
        return self.status == "STRICT_RELAY_READY"

    def safe_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "timezone_assumed_fields": list(self.timezone_assumed_fields),
            "payload_ref": self.payload_ref,
            "production_send": "blocked",
        }


def validate_strict_payload(payload: dict[str, Any], *, assume_bangkok_if_naive: bool = False) -> RelayValidation:
    """Validate one OUTAGE or RESTORE payload without generating or emitting identifiers."""
    reasons: list[str] = []
    assumed: list[str] = []
    event_type = _meter_state_event_type(payload)
    if event_type not in {"OUTAGE", "RESTORE"}:
        reasons.append("event_type_required")
    _required_text(payload, "request_id", MAX_REQUEST_ID, reasons)
    _required_text(payload, "meter_no", MAX_METER, reasons)
    _timestamp(payload, "timestamp", reasons, assumed, assume_bangkok_if_naive)
    if event_type == "OUTAGE" and _text(payload.get("outage_at")):
        _timestamp(payload, "outage_at", reasons, assumed, assume_bangkok_if_naive)
    if event_type == "RESTORE" and _text(payload.get("restore_at")):
        _timestamp(payload, "restore_at", reasons, assumed, assume_bangkok_if_naive)
    return _result(payload, reasons, assumed)


def validate_strict_pair(
    outage_payload: dict[str, Any],
    restore_payload: dict[str, Any],
    *,
    assume_bangkok_if_naive: bool = False,
) -> RelayValidation:
    """Validate a prospective pair; the caller must supply source identifiers from upstream."""
    reasons: list[str] = []
    assumed: list[str] = []
    outage = validate_strict_payload(outage_payload, assume_bangkok_if_naive=assume_bangkok_if_naive)
    restore = validate_strict_payload(restore_payload, assume_bangkok_if_naive=assume_bangkok_if_naive)
    reasons.extend(outage.reason_codes)
    reasons.extend(restore.reason_codes)
    assumed.extend(outage.timezone_assumed_fields)
    assumed.extend(restore.timezone_assumed_fields)
    if _text(outage_payload.get("event_type")).upper() != "OUTAGE":
        reasons.append("outage_event_type_required")
    if _text(restore_payload.get("event_type")).upper() != "RESTORE":
        reasons.append("restore_event_type_required")
    if _text(outage_payload.get("meter_no")) != _text(restore_payload.get("meter_no")):
        reasons.append("meter_identity_mismatch")
    if _site_reference(outage_payload) and _site_reference(restore_payload) and _site_reference(outage_payload) != _site_reference(restore_payload):
        reasons.append("site_identity_mismatch")
    outage_at = _parsed_timestamp(outage_payload.get("outage_at") or outage_payload.get("timestamp"), assume_bangkok_if_naive)
    restore_at = _parsed_timestamp(restore_payload.get("restore_at") or restore_payload.get("timestamp"), assume_bangkok_if_naive)
    if outage_at is not None and restore_at is not None:
        duration = (restore_at - outage_at).total_seconds() / 60.0
        if duration <= 0:
            reasons.append("restore_must_follow_outage")
        elif duration <= MIN_DURATION_MINUTES or duration > MAX_DURATION_MINUTES:
            reasons.append("duration_out_of_range")
    return _result({"outage": outage_payload, "restore": restore_payload}, reasons, assumed)


def _result(payload: dict[str, Any], reasons: list[str], assumed: list[str]) -> RelayValidation:
    unique_reasons = tuple(sorted(set(reasons)))
    return RelayValidation(
        status="STRICT_RELAY_READY" if not unique_reasons else "REVIEW_REQUIRED",
        reason_codes=unique_reasons,
        timezone_assumed_fields=tuple(sorted(set(assumed))),
        payload_ref="relay_" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()[:20],
    )


def _required_text(payload: dict[str, Any], field: str, max_length: int, reasons: list[str]) -> None:
    value = _text(payload.get(field))
    if not value:
        reasons.append(f"{field}_required")
    elif len(value) > max_length:
        reasons.append(f"{field}_too_long")


def _bounded_text(value: Any, max_length: int) -> str:
    text = _text(value)
    return text if text and len(text) <= max_length else ""


def _timestamp(payload: dict[str, Any], field: str, reasons: list[str], assumed: list[str], allow_assume: bool) -> None:
    value = _text(payload.get(field))
    if not value:
        reasons.append(f"{field}_timestamp_required")
        return
    if _is_naive_timestamp(value):
        if allow_assume:
            assumed.append(field)
        else:
            reasons.append(f"{field}_timezone_offset_required")
        return
    if _parsed_timestamp(value, allow_assume) is None:
        reasons.append(f"{field}_timestamp_required")


def _parsed_timestamp(value: Any, allow_assume: bool) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None and not allow_assume:
        return None
    return parsed


def _is_naive_timestamp(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    if text.endswith("Z"):
        return False
    try:
        return datetime.fromisoformat(text).tzinfo is None
    except ValueError:
        return False


def _site_reference(payload: dict[str, Any]) -> str:
    return _text(payload.get("site_id")) or _text(payload.get("location_id"))


def _meter_state_event_type(payload: dict[str, Any]) -> str:
    explicit = _text(payload.get("event_type")).upper()
    if explicit in {"OUTAGE", "RESTORE"}:
        return explicit
    mapped = _text(payload.get("power_status") or payload.get("event_status") or payload.get("status")).lower()
    if mapped in {"outage", "power_off", "power off", "off", "down", "ac_main_fail", "ac main fail", "fail", "failure"}:
        return "OUTAGE"
    if mapped in {"restore", "restored", "power_on", "power on", "on", "normal", "recover", "recovered"}:
        return "RESTORE"
    return "UNKNOWN"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("input must be a JSON object")
    return payload


def self_test() -> None:
    outage = {
        "request_id": "OUT-1",
        "source_event_id": "UPSTREAM-INCIDENT-1",
        "event_type": "OUTAGE",
        "meter_no": "REDACTED-METER-0000",
        "site_id": "REDACTED-SITE-0000",
        "timestamp": "2026-07-10T10:00:00+07:00",
        "outage_at": "2026-07-10T10:00:00+07:00",
    }
    restore = {
        **outage,
        "request_id": "RESTORE-1",
        "event_type": "RESTORE",
        "timestamp": "2026-07-10T11:00:00+07:00",
        "restore_at": "2026-07-10T11:00:00+07:00",
    }
    assert validate_strict_pair(outage, restore).valid
    assert "source_event_id_required" in validate_strict_payload({**outage, "source_event_id": ""}).reason_codes
    assert "source_event_id_mismatch" in validate_strict_pair(outage, {**restore, "source_event_id": "other"}).reason_codes
    assert "timestamp_timezone_offset_required" in validate_strict_payload({**outage, "timestamp": "2026-07-10T10:00:00"}).reason_codes
    safe = validate_strict_payload(outage).safe_dict()
    assert "REDACTED-METER-0000" not in json.dumps(safe)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate strict PEA relay payloads without emitting raw identifiers.")
    parser.add_argument("--input", type=Path, help="One OUTAGE or RESTORE JSON payload")
    parser.add_argument("--pair-input", type=Path, help="JSON object with outage and restore payloads")
    parser.add_argument("--assume-bangkok-if-naive", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("self-test: PASS")
        return
    if bool(args.input) == bool(args.pair_input):
        parser.error("provide exactly one of --input or --pair-input")
    if args.input:
        result = validate_strict_payload(_load_json(args.input), assume_bangkok_if_naive=args.assume_bangkok_if_naive)
    else:
        pair = _load_json(args.pair_input)
        outage = pair.get("outage")
        restore = pair.get("restore")
        if not isinstance(outage, dict) or not isinstance(restore, dict):
            parser.error("pair input must contain outage and restore objects")
        result = validate_strict_pair(outage, restore, assume_bangkok_if_naive=args.assume_bangkok_if_naive)
    print(json.dumps(result.safe_dict(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
