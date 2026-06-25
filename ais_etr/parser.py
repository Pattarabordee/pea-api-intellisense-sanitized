from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from .config import PILOT_DISTRICTS
from .schemas import OutageDevice, OutageEvent
from .utils import normalize_device_id, normalize_feeder, stable_id


OUTAGE_KEYWORDS = (
    "ไฟดับ",
    "ไฟฟ้าขัดข้อง",
    "กระแสไฟฟ้าขัดข้อง",
    "ระบบไฟฟ้าขัดข้อง",
    "ไฟตก",
    "outage",
    "trip",
    "tripped",
    "operate",
    "operated",
    "fault",
    "d/f",
    "recloser",
    "reclosure",
    "re-closer",
    "cb",
)

NEGATIVE_OUTAGE_PATTERNS = (
    r"ไม่มีเหตุไฟดับ",
    r"ไม่มีไฟดับ",
    r"ไม่พบเหตุไฟดับ",
    r"not\s+an?\s+outage",
)

DEVICE_PATTERNS = (
    r"\b[A-Z]{3}\d{2}VB[-/][A-Z0-9/.-]+\b",
    r"\b[A-Z]{3}\d{2}VR[-/][A-Z0-9/.-]+\b",
    r"\b[A-Z]{3}\d{2}VF[-/][A-Z0-9/.-]+\b",
    r"\b[A-Z]{3}\d{2}[A-Z]{1,3}[-/][A-Z0-9/.-]+\b",
    r"\b[A-Z]{3}\d{2}[A-Z]{1,3}-\d+\b",
    r"\b21[A-Z0-9]{2,}[A-Z]{2}[A-Z0-9-]*\b",
    r"\b2147[A-Z]{2}\d+\b",
    r"\bTR\d{2}-\d+\b",
    r"\b\d{2}-\d{6}\b",
)

FEEDER_RE = re.compile(r"\b([A-Z]{3}\d{2})\b", re.IGNORECASE)
EVENT_NUMBER_CANDIDATE_RE = re.compile(r"\b\d{8,12}\b")

REAL_DISTRICT_ALIASES = {
    "พังโคน": ("พังโคน", "อ.พังโคน", "อำเภอพังโคน", "(พังโคน)"),
    "วาริชภูมิ": ("วาริชภูมิ", "อ.วาริชภูมิ", "อำเภอวาริชภูมิ", "(วาริชภูมิ)"),
    "นิคมน้ำอูน": ("นิคมน้ำอูน", "อ.นิคมน้ำอูน", "อำเภอนิคมน้ำอูน", "(นิคมน้ำอูน)"),
}
EVENT_NUMBER_RE = re.compile(
    r"(?:event\s*(?:id|number)?|eventno|เลข(?:ที่)?เหตุการณ์|เหตุการณ์)\s*[:#：]?\s*(\d{8,12})",
    re.IGNORECASE,
)
TIMESTAMP_RE = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?)")
OPERATION_CONTEXT_RE = re.compile(
    r"\b(trip|open|close|operate|operated|lockout|in\s+progress|switching|executed|fail|alarm)\b|"
    r"(earth_fault|phase_flt|recl_operate|recl_lockout|ar_operate|ar_lck|switch status|circuit breaker status)",
    re.IGNORECASE,
)
TELEMETRY_CONTEXT_RE = re.compile(
    r"(\[normal\]|\[high\]|\[low\]|fault current|current phase|active power|reactive power|fault location|\bmw\b|\bmvar\b)",
    re.IGNORECASE,
)


def looks_like_outage(text: str) -> bool:
    lowered = text.lower()
    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in NEGATIVE_OUTAGE_PATTERNS):
        return False
    return any(keyword.lower() in lowered for keyword in OUTAGE_KEYWORDS)


def extract_device_id(text: str) -> str | None:
    for pattern in DEVICE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return normalize_device_id(match.group(0))
    return None


def classify_device(device_id: str | None, text: str) -> str:
    lowered = text.lower()
    did = device_id or ""
    if re.search(r"\bcb\b|circuit\s*breaker|เซอร์กิต|เบรกเกอร์", lowered) or "VB" in did:
        return "CB"
    if re.search(r"recloser|reclosure|รีโคล", lowered) or "VR" in did or "RC" in did:
        return "Recloser"
    if re.search(r"switch|drop\s*out|fuse|d/f|สวิต|ฟิวส์", lowered) or "SW" in did or "VF" in did:
        return "Switch"
    if re.search(r"transformer|หม้อแปลง", lowered) or "XF" in did or did.startswith("TR"):
        return "Transformer"
    if re.search(r"\b[A-Z]{3}\d{2}F[-/]", did):
        return "Switch"
    return "Unknown"


def extract_feeder(text: str, device_id: str | None) -> str | None:
    if device_id:
        feeder = normalize_feeder(device_id[:5])
        if feeder:
            return feeder
    match = FEEDER_RE.search(text)
    if match:
        return normalize_feeder(match.group(1))
    return None


def extract_district(text: str, districts: tuple[str, ...] = PILOT_DISTRICTS) -> str | None:
    for district in districts:
        if district in text or f"อ.{district}" in text or f"อำเภอ{district}" in text:
            return district
    return None


def extract_real_district_alias(text: str) -> str | None:
    for district, aliases in REAL_DISTRICT_ALIASES.items():
        if any(alias in text for alias in aliases):
            return district
    return None


def extract_district_from_context(
    message: dict[str, Any],
    districts: tuple[str, ...] = PILOT_DISTRICTS,
) -> str | None:
    context_parts = []
    for key in ("roomDistrict", "room_district", "roomTitle", "room_title", "roomName", "spaceTitle"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            context_parts.append(value)
    if not context_parts:
        return None
    context_text = " ".join(context_parts)
    return extract_district(context_text, districts) or extract_real_district_alias(context_text)


def extract_event_number(text: str) -> str | None:
    match = EVENT_NUMBER_RE.search(text)
    return match.group(1) if match else None


def event_number_missing_reason(text: str, event_number: str | None) -> str | None:
    if event_number:
        return None
    if EVENT_NUMBER_CANDIDATE_RE.search(text):
        return "number_present_without_event_label"
    return "not_present_in_message"


def extract_event_time(text: str, fallback: str | None = None) -> str | None:
    value, _source = extract_event_time_with_source(text, fallback=fallback)
    return value


def extract_event_time_with_source(text: str, fallback: str | None = None) -> tuple[str | None, str | None]:
    candidates = _timestamp_candidates(text)
    for value, context in candidates:
        if _is_operation_context(context):
            return value, "operation_row"
    if candidates:
        return candidates[0][0], "first_timestamp"

    patterns = (
        r"(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2})",
        r"(\d{1,2}-\d{1,2}-\d{4}\s+\d{1,2}:\d{2})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M"):
            try:
                return datetime.strptime(value.replace("T", " "), fmt).isoformat(), "legacy_timestamp"
            except ValueError:
                pass
    return fallback, "message_created" if fallback else None


def _timestamp_candidates(text: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    matches = list(TIMESTAMP_RE.finditer(text))
    for index, match in enumerate(matches):
        value = match.group(1)
        parsed = _parse_absolute_timestamp(value)
        if parsed is None:
            continue
        next_newline = text.find("\n", match.end())
        next_timestamp = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        context_candidates = [next_timestamp]
        if next_newline != -1:
            context_candidates.append(next_newline)
        context_end = min(context_candidates)
        context = text[match.end() : context_end]
        candidates.append((parsed.isoformat(), context[:240]))
    return candidates


def _parse_absolute_timestamp(value: str) -> datetime | None:
    value = value.replace("T", " ")
    if "." in value:
        head, tail = value.split(".", 1)
        value = head + "." + tail[:6]
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return None


def _is_operation_context(context: str) -> bool:
    if not OPERATION_CONTEXT_RE.search(context):
        return False
    if TELEMETRY_CONTEXT_RE.search(context) and not re.search(
        r"\b(trip|open|close|operate|operated|lockout|in\s+progress|switching|executed|fail|alarm)\b",
        context,
        re.IGNORECASE,
    ):
        return False
    return True


def extract_device_operation_state(text: str) -> dict[str, Any]:
    first_open: datetime | None = None
    first_close_after_open: datetime | None = None
    has_trip = False
    has_lockout = False
    for value, context in _timestamp_candidates(text):
        event_dt = _parse_absolute_timestamp(value)
        if event_dt is None:
            continue
        lowered = context.lower()
        if re.search(r"\btrip\b|earth_fault|phase_flt", lowered):
            has_trip = True
        if re.search(r"\blockout\b|ar_lck|recl_lockout", lowered):
            has_lockout = True
        if first_open is None and re.search(r"\bopen\b", lowered):
            first_open = event_dt
            continue
        if first_open is not None and first_close_after_open is None and re.search(r"\bclose\b", lowered):
            if event_dt >= first_open:
                first_close_after_open = event_dt

    open_close_minutes = None
    if first_open and first_close_after_open:
        open_close_minutes = round((first_close_after_open - first_open).total_seconds() / 60, 2)

    if has_lockout or (first_open and not first_close_after_open):
        device_class = "sustained_candidate"
    elif open_close_minutes is not None and open_close_minutes <= 1:
        device_class = "momentary_le_1m"
    elif open_close_minutes is not None and open_close_minutes <= 5:
        device_class = "short_le_5m"
    elif open_close_minutes is not None:
        device_class = "open_gt_5m"
    elif has_trip:
        device_class = "trip_no_open_close"
    else:
        device_class = "unknown"

    return {
        "webex_device_interruption_class": device_class,
        "webex_open_close_minutes": open_close_minutes,
        "webex_has_lockout": has_lockout,
    }


def parse_webex_message(
    message: dict[str, Any],
    districts: tuple[str, ...] = PILOT_DISTRICTS,
) -> OutageEvent | None:
    text = message.get("text") or message.get("markdown") or ""
    if not text.strip():
        return None
    device_id = extract_device_id(text)
    if not device_id and not looks_like_outage(text):
        return None

    feeder = extract_feeder(text, device_id)
    device_type = classify_device(device_id, text)
    event_number = extract_event_number(text)
    created = message.get("created")
    event_time, event_time_source = extract_event_time_with_source(text, fallback=created)
    operation_state = extract_device_operation_state(text)
    district = extract_district(text, districts) or extract_real_district_alias(text)
    district_source = "message_text" if district else None
    if not district:
        district = extract_district_from_context(message, districts)
        district_source = "room_context" if district else None
    source = str(message.get("source") or "webex")
    event_id = stable_id(source, message.get("id"), device_id, event_time, text[:80])

    return OutageEvent(
        event_id=event_id,
        source=source,
        webex_message_id=message.get("id"),
        room_id=message.get("roomId"),
        raw_text=text,
        created=created,
        event_time=event_time,
        district=district,
        site=district,
        outage_device=OutageDevice(device_type=device_type, device_id=device_id, feeder=feeder),
        parsed_fields={
            "looks_like_outage": looks_like_outage(text),
            "districts_scanned": list(districts),
            "district_source": district_source,
            "event_number": event_number,
            "event_number_missing_reason": event_number_missing_reason(text, event_number),
            "event_time_source": event_time_source,
            **operation_state,
        },
    )
