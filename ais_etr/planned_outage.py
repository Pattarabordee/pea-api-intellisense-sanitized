from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

from .schemas import OutageDevice, OutageEvent
from .utils import normalize_device_id, stable_id


COL_EVENT_NUMBER = "หมายเลขเหตุการณ์"
COL_REGION = "เขต"
COL_WORK_CENTER = "กฟฟ.จุดรวมงาน"
COL_RESPONSIBLE_OFFICE = "กฟฟ.ที่รับผิดชอบ"
COL_DEVICE_ID = "รหัสอุปกรณ์"
COL_SCHEDULED_START = "กำหนดการเริ่มดับไฟ"
COL_NOTICE_TIME = "ประกาศดับไฟ (NO)"
COL_OPERATION_TIME = "ดำเนินการ (IP)"
COL_BUSINESS_DAYS = "วันทำการ"
COL_NOTICE_STATUS = "สถานะการแจ้ง"
COL_SEND_STATUS = "การกดส่งข้อมูล"
COL_CONTACT_CENTER_SENT_AT = "ส่งข้อมูลไป ContactCenter/SmartPlus"

REQUIRED_COLUMNS = (
    COL_EVENT_NUMBER,
    COL_REGION,
    COL_WORK_CENTER,
    COL_RESPONSIBLE_OFFICE,
    COL_DEVICE_ID,
    COL_SCHEDULED_START,
)

_EMPTY_VALUES = {"", "-", "nan", "none", "null"}
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
)


@dataclass(frozen=True)
class PlannedOutage:
    event_number: str
    area: str
    region: str | None
    work_center: str | None
    responsible_office: str | None
    device_id: str
    scheduled_start: datetime
    reference_time: datetime
    lead_days: float
    notice_time: datetime | None = None
    operation_time: datetime | None = None
    business_days: int | None = None
    notice_status: str | None = None
    send_status: str | None = None
    contact_center_sent_at: datetime | None = None
    raw: dict[str, str] = field(default_factory=dict, repr=False)

    def to_event(self) -> OutageEvent:
        fields = self.payload_fields()
        return OutageEvent(
            event_id=stable_id(
                "planned-outage",
                self.event_number,
                self.device_id,
                self.scheduled_start.isoformat(sep=" "),
            ),
            source="planned_outage",
            webex_message_id=None,
            room_id=None,
            raw_text=json.dumps(self.raw, ensure_ascii=False, sort_keys=True),
            outage_device=OutageDevice(
                device_type="Transformer",
                device_id=self.device_id,
                feeder=None,
            ),
            event_time=self.scheduled_start.isoformat(sep=" "),
            district=self.area,
            site=self.area,
            parsed_fields=fields,
        )

    def payload_fields(self) -> dict[str, Any]:
        return {
            "planned_outage_no": self.event_number,
            "area": self.area,
            "region": self.region,
            "work_center": self.work_center,
            "responsible_office": self.responsible_office,
            "scheduled_start": self.scheduled_start.isoformat(sep=" "),
            "reference_time": self.reference_time.isoformat(sep=" "),
            "lead_days": round(self.lead_days, 3),
            "notice_time": _format_dt(self.notice_time),
            "operation_time": _format_dt(self.operation_time),
            "business_days": self.business_days,
            "notice_status": self.notice_status,
            "send_status": self.send_status,
            "contact_center_sent_at": _format_dt(self.contact_center_sent_at),
        }


def iter_planned_outage_rows(path: str | Path) -> Iterator[dict[str, str]]:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_columns(reader.fieldnames)
        for row in reader:
            yield {key: _cell(row, key) for key in reader.fieldnames or ()}


def pick_planned_area(row: dict[str, str], districts: Iterable[str]) -> str | None:
    responsible_office = _cell(row, COL_RESPONSIBLE_OFFICE)
    if _has_value(responsible_office):
        return _match_district(responsible_office, districts)

    work_center = _cell(row, COL_WORK_CENTER)
    if _has_value(work_center):
        return _match_district(work_center, districts)

    return _match_district(_cell(row, COL_REGION), districts)


def planned_outage_from_row(
    row: dict[str, str],
    area: str,
    reference_time: datetime,
) -> PlannedOutage:
    scheduled_start = _required_datetime(row, COL_SCHEDULED_START)
    device_id = normalize_device_id(_cell(row, COL_DEVICE_ID))
    if not device_id or device_id in {"NAN", "NONE", "NULL"}:
        raise ValueError(f"missing planned outage device in column {COL_DEVICE_ID}")

    lead_days = (scheduled_start - reference_time).total_seconds() / 86400
    return PlannedOutage(
        event_number=_cell(row, COL_EVENT_NUMBER),
        area=area,
        region=_optional_text(row, COL_REGION),
        work_center=_optional_text(row, COL_WORK_CENTER),
        responsible_office=_optional_text(row, COL_RESPONSIBLE_OFFICE),
        device_id=device_id,
        scheduled_start=scheduled_start,
        reference_time=reference_time,
        lead_days=lead_days,
        notice_time=_optional_datetime(row, COL_NOTICE_TIME),
        operation_time=_optional_datetime(row, COL_OPERATION_TIME),
        business_days=_optional_int(row, COL_BUSINESS_DAYS),
        notice_status=_optional_text(row, COL_NOTICE_STATUS),
        send_status=_optional_text(row, COL_SEND_STATUS),
        contact_center_sent_at=_optional_datetime(row, COL_CONTACT_CENTER_SENT_AT),
        raw=dict(row),
    )


def _validate_columns(fieldnames: list[str] | None) -> None:
    fields = set(fieldnames or ())
    missing = [column for column in REQUIRED_COLUMNS if column not in fields]
    if missing:
        raise ValueError(f"planned outage CSV missing required columns: {', '.join(missing)}")


def _match_district(text: str, districts: Iterable[str]) -> str | None:
    for district in districts:
        if district and district in text:
            return district
    return None


def _cell(row: dict[str, Any], column: str) -> str:
    value = row.get(column)
    return "" if value is None else str(value).strip()


def _has_value(value: str) -> bool:
    return value.strip().lower() not in _EMPTY_VALUES


def _optional_text(row: dict[str, str], column: str) -> str | None:
    value = _cell(row, column)
    return value if _has_value(value) else None


def _parse_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not _has_value(text):
        return None
    normalized = text.replace("T", " ")
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _required_datetime(row: dict[str, str], column: str) -> datetime:
    value = _cell(row, column)
    parsed = _parse_datetime(value)
    if parsed is None:
        raise ValueError(f"invalid datetime in column {column}: {value!r}")
    return parsed


def _optional_datetime(row: dict[str, str], column: str) -> datetime | None:
    return _parse_datetime(_cell(row, column))


def _optional_int(row: dict[str, str], column: str) -> int | None:
    value = _cell(row, column)
    if not _has_value(value):
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _format_dt(value: datetime | None) -> str | None:
    return value.isoformat(sep=" ") if value else None
