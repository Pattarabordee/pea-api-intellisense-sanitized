from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class OutageDevice:
    device_type: str
    device_id: str | None = None
    feeder: str | None = None

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OutageEvent:
    event_id: str
    source: str
    webex_message_id: str | None
    room_id: str | None
    raw_text: str
    outage_device: OutageDevice
    created: str | None = None
    event_time: str | None = None
    district: str | None = None
    site: str | None = None
    parsed_fields: dict[str, Any] = field(default_factory=dict)

    def asdict(self) -> dict[str, Any]:
        data = asdict(self)
        data["outage_device"] = self.outage_device.asdict()
        return data


@dataclass(frozen=True)
class CustomerAsset:
    peano: str
    customer: str = "AIS"
    feeder: str | None = None
    meter_location: str | None = None
    transformer_id: str | None = None
    transformer_peano: str | None = None
    recloser_ids: tuple[str, ...] = ()
    switch_ids: tuple[str, ...] = ()
    cb_ids: tuple[str, ...] = ()
    trace_status: str | None = None
    confidence_eligible: bool = False

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CustomerMatch:
    customer: str
    peano: str
    feeder: str | None
    match_level: str

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatchResult:
    matches: tuple[CustomerMatch, ...]
    match_level: str | None
    match_confidence: float

    def asdict(self) -> dict[str, Any]:
        return {
            "matches": [match.asdict() for match in self.matches],
            "match_level": self.match_level,
            "match_confidence": self.match_confidence,
        }


@dataclass(frozen=True)
class Prediction:
    etr_minutes_p50: float
    q25: float
    q75: float
    q10: float
    q90: float
    risk_level: str
    model_version: str

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NotificationRecord:
    payload: dict[str, Any]
    status: str
    status_code: int | None = None
    response_text: str | None = None

