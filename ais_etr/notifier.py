from __future__ import annotations

import json
import urllib.error
import urllib.request

from .notification_policy import build_customer_facing_gate
from .schemas import MatchResult, NotificationRecord, OutageEvent, Prediction, utc_now_iso


def build_notification_payload(
    event: OutageEvent,
    match_result: MatchResult,
    prediction: Prediction,
    mode: str = "shadow",
) -> dict:
    parsed_fields = event.parsed_fields or {}
    shadow_policy = build_customer_facing_gate(
        webex_device_interruption_class=parsed_fields.get("webex_device_interruption_class"),
        webex_open_close_minutes=parsed_fields.get("webex_open_close_minutes"),
        match_level=match_result.match_level,
        match_confidence=match_result.match_confidence,
        affected_count=len(match_result.matches),
    )
    return {
        "mode": mode,
        "event_id": event.event_id,
        "source": {
            "webex_message_id": event.webex_message_id,
            "room_id": event.room_id,
        },
        "outage_device": {
            "type": event.outage_device.device_type,
            "id": event.outage_device.device_id,
            "feeder": event.outage_device.feeder,
        },
        "affected_customers": [match.asdict() for match in match_result.matches],
        "prediction": {
            "etr_minutes_p50": prediction.etr_minutes_p50,
            "q25": prediction.q25,
            "q75": prediction.q75,
            "q10": prediction.q10,
            "q90": prediction.q90,
            "risk_level": prediction.risk_level,
            "match_confidence": match_result.match_confidence,
            "model_version": prediction.model_version,
        },
        "shadow_policy": shadow_policy,
        "generated_at": utc_now_iso(),
    }


def build_planned_outage_payload(
    event: OutageEvent,
    match_result: MatchResult,
    planned_fields: dict,
    mode: str = "shadow",
) -> dict:
    return {
        "mode": mode,
        "type": "planned_outage",
        "event_id": event.event_id,
        "source": {
            "system": "PEA ReportPO",
            "planned_outage_no": planned_fields.get("planned_outage_no"),
        },
        "area": {
            "district": event.district,
            "region": planned_fields.get("region"),
            "work_center": planned_fields.get("work_center"),
            "responsible_office": planned_fields.get("responsible_office"),
        },
        "planned_outage": {
            "scheduled_start": planned_fields.get("scheduled_start"),
            "reference_time": planned_fields.get("reference_time"),
            "lead_days": planned_fields.get("lead_days"),
            "minimum_lead_days": planned_fields.get("minimum_lead_days"),
            "notice_time": planned_fields.get("notice_time"),
            "operation_time": planned_fields.get("operation_time"),
            "business_days": planned_fields.get("business_days"),
            "notice_status": planned_fields.get("notice_status"),
            "send_status": planned_fields.get("send_status"),
            "contact_center_sent_at": planned_fields.get("contact_center_sent_at"),
        },
        "outage_device": {
            "type": event.outage_device.device_type,
            "id": event.outage_device.device_id,
            "feeder": event.outage_device.feeder,
        },
        "affected_customers": [match.asdict() for match in match_result.matches],
        "match": {
            "level": match_result.match_level,
            "confidence": match_result.match_confidence,
            "affected_count": len(match_result.matches),
        },
        "generated_at": utc_now_iso(),
    }


class ShadowNotifier:
    """Posts only shadow-mode payloads to a mock endpoint."""

    def __init__(self, endpoint_url: str | None, timeout: int = 20):
        self.endpoint_url = endpoint_url
        self.timeout = timeout

    def send(self, payload: dict) -> NotificationRecord:
        if payload.get("mode") != "shadow":
            raise ValueError("This MVP notifier only allows shadow-mode payloads")
        if not self.endpoint_url:
            return NotificationRecord(payload=payload, status="SKIPPED_NO_ENDPOINT")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint_url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return NotificationRecord(
                    payload=payload,
                    status="SENT",
                    status_code=resp.status,
                    response_text=body[:1000],
                )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return NotificationRecord(
                payload=payload,
                status="HTTP_ERROR",
                status_code=exc.code,
                response_text=body[:1000],
            )
        except Exception as exc:
            return NotificationRecord(payload=payload, status="ERROR", response_text=str(exc)[:1000])
