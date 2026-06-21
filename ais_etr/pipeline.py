from __future__ import annotations

from collections import Counter
import csv
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any

from .config import Settings, ensure_runtime_dirs
from .db import RuntimeDb
from .matcher import ProtectionMatcher
from .model import EtrPredictor, train_and_save
from .notifier import ShadowNotifier, build_notification_payload, build_planned_outage_payload
from .parser import parse_webex_message
from .planned_outage import iter_planned_outage_rows, pick_planned_area, planned_outage_from_row
from .registry import load_assets_from_upstream_result, registry_summary
from .schemas import NotificationRecord
from .webex import WebexClient, WebexOAuthTokenManager


@dataclass(frozen=True)
class PollResult:
    fetched: int
    new_messages: int
    parsed_events: int
    notifications: int
    skipped: int


@dataclass(frozen=True)
class PollLoopResult:
    iterations: int
    fetched: int
    new_messages: int
    parsed_events: int
    notifications: int
    skipped: int


@dataclass(frozen=True)
class PlannedOutageRunResult:
    source: str
    reference_time: str
    min_lead_days: int
    rows_read: int
    target_area_rows: int
    eligible_rows: int
    matched_events: int
    notifications: int
    skipped_outside_area: int
    skipped_too_soon: int
    skipped_invalid: int
    skipped_existing: int
    skipped_no_match: int
    target_area_counts: dict[str, int]
    area_counts: dict[str, int]
    notification_status: dict[str, int]


@dataclass(frozen=True)
class WebexHistoryReplayResult:
    source: str
    rows_read: int
    new_messages: int
    parsed_events: int
    predictions: int
    notifications_captured: int
    skipped_existing: int
    skipped_missing_id: int
    skipped_unparsed: int
    affected_events: int
    affected_customers_total: int
    match_level_counts: dict[str, int]
    risk_level_counts: dict[str, int]
    notification_status: dict[str, int]
    audit_output: str | None


class AisEtrPipeline:
    def __init__(
        self,
        settings: Settings,
        db: RuntimeDb | None = None,
        webex_client: Any | None = None,
        notifier: ShadowNotifier | None = None,
    ):
        self.settings = settings
        ensure_runtime_dirs(settings)
        self.db = db or RuntimeDb(settings.resolve(settings.db_path))
        self.webex_client = webex_client
        self.notifier = notifier or ShadowNotifier(settings.mock_webhook_url)

    def init_db(self) -> None:
        self.db.init()

    def build_registry(self, path: str | Path | None = None) -> dict[str, int]:
        self.db.init()
        assets = load_assets_from_upstream_result(self.settings.resolve(path or self.settings.registry_path))
        count = self.db.upsert_customer_assets(assets)
        summary = registry_summary(assets)
        summary["upserted"] = count
        return summary

    def train_model(self) -> dict[str, Any]:
        self.db.init()
        result = train_and_save(
            self.settings.resolve(self.settings.event_file),
            [self.settings.resolve(path) for path in self.settings.etr_files],
            self.settings.resolve(self.settings.distance_file),
            self.settings.resolve(self.settings.model_path),
        )
        self.db.insert_model_run(
            result.model_version,
            result.estimator,
            result.status,
            result.metrics,
            result.artifact_path,
        )
        return {
            "model_version": result.model_version,
            "estimator": result.estimator,
            "status": result.status,
            "metrics": result.metrics,
            "artifact_path": str(result.artifact_path),
        }

    def poll_once(self, max_messages: int = 50) -> PollResult:
        self.db.init()
        client = self._webex_client()
        messages = client.list_messages(max_items=max_messages)
        assets = self.db.load_customer_assets()
        matcher = ProtectionMatcher(assets)
        predictor = EtrPredictor.load(self.settings.resolve(self.settings.model_path))

        fetched = len(messages)
        new_messages = parsed_events = notifications = skipped = 0
        for message in messages:
            message_id = message.get("id")
            if not message_id:
                skipped += 1
                continue
            if not self.db.insert_webex_message(message):
                skipped += 1
                continue
            new_messages += 1
            parse_message = message
            if self.settings.webex_room_district:
                parse_message = {**message, "roomDistrict": self.settings.webex_room_district}
            event = parse_webex_message(parse_message, districts=self.settings.pilot_districts)
            if event is None:
                self.db.mark_message_processed(message_id)
                skipped += 1
                continue
            parsed_events += 1
            self.db.upsert_event(event)
            match_result = matcher.match(event)
            prediction = predictor.predict(event, match_result)
            self.db.insert_prediction(event.event_id, prediction, match_result)
            payload = build_notification_payload(
                event,
                match_result,
                prediction,
                mode=self.settings.notification_mode,
            )
            record = self.notifier.send(payload)
            self.db.insert_notification(
                event.event_id,
                self.settings.mock_webhook_url,
                self.settings.notification_mode,
                record,
            )
            self.db.mark_message_processed(message_id)
            notifications += 1
        return PollResult(
            fetched=fetched,
            new_messages=new_messages,
            parsed_events=parsed_events,
            notifications=notifications,
            skipped=skipped,
        )

    def notify_planned_outages(
        self,
        path: str | Path | None = None,
        reference_time: datetime | None = None,
        min_lead_days: int | None = None,
        limit: int | None = None,
    ) -> PlannedOutageRunResult:
        self.db.init()
        source = self.settings.resolve(path or self.settings.planned_outage_file)
        reference = (reference_time or datetime.now()).replace(microsecond=0)
        lead_days = min_lead_days if min_lead_days is not None else self.settings.planned_notice_min_days
        matcher = ProtectionMatcher(self.db.load_customer_assets())

        rows_read = target_area_rows = eligible_rows = matched_events = notifications = 0
        skipped_outside_area = skipped_too_soon = skipped_invalid = skipped_existing = skipped_no_match = 0
        target_area_counts: dict[str, int] = {}
        area_counts: dict[str, int] = {}
        notification_status: dict[str, int] = {}

        for row in iter_planned_outage_rows(source):
            rows_read += 1
            area = pick_planned_area(row, self.settings.pilot_districts)
            if not area:
                skipped_outside_area += 1
                continue
            target_area_rows += 1
            target_area_counts[area] = target_area_counts.get(area, 0) + 1
            try:
                planned = planned_outage_from_row(row, area, reference)
            except ValueError:
                skipped_invalid += 1
                continue
            if planned.lead_days < lead_days:
                skipped_too_soon += 1
                continue

            eligible_rows += 1
            area_counts[area] = area_counts.get(area, 0) + 1
            event = planned.to_event()
            if self.db.notification_exists(event.event_id, self.settings.notification_mode):
                skipped_existing += 1
                continue

            match_result = matcher.match(event)
            if match_result.matches:
                matched_events += 1
            elif self.settings.planned_require_asset_match:
                skipped_no_match += 1
                continue

            planned_fields = planned.payload_fields()
            planned_fields["minimum_lead_days"] = lead_days
            payload = build_planned_outage_payload(
                event,
                match_result,
                planned_fields,
                mode=self.settings.notification_mode,
            )
            self.db.upsert_event(event)
            record = self.notifier.send(payload)
            self.db.insert_notification(
                event.event_id,
                self.settings.mock_webhook_url,
                self.settings.notification_mode,
                record,
            )
            notification_status[record.status] = notification_status.get(record.status, 0) + 1
            notifications += 1
            if limit is not None and notifications >= limit:
                break

        return PlannedOutageRunResult(
            source=str(source),
            reference_time=reference.isoformat(sep=" "),
            min_lead_days=lead_days,
            rows_read=rows_read,
            target_area_rows=target_area_rows,
            eligible_rows=eligible_rows,
            matched_events=matched_events,
            notifications=notifications,
            skipped_outside_area=skipped_outside_area,
            skipped_too_soon=skipped_too_soon,
            skipped_invalid=skipped_invalid,
            skipped_existing=skipped_existing,
            skipped_no_match=skipped_no_match,
            target_area_counts=target_area_counts,
            area_counts=area_counts,
            notification_status=notification_status,
        )

    def replay_webex_history(
        self,
        source: str | Path,
        limit: int | None = None,
        audit_output: str | Path | None = None,
        reprocess_existing: bool = False,
        capture_notifications: bool = True,
    ) -> WebexHistoryReplayResult:
        self.db.init()
        source_path = self.settings.resolve(source)
        assets = self.db.load_customer_assets()
        matcher = ProtectionMatcher(assets)
        predictor = EtrPredictor.load(self.settings.resolve(self.settings.model_path))

        rows_read = new_messages = parsed_events = predictions = notifications_captured = 0
        skipped_existing = skipped_missing_id = skipped_unparsed = 0
        affected_events = affected_customers_total = 0
        match_level_counts: Counter[str] = Counter()
        risk_level_counts: Counter[str] = Counter()
        notification_status: Counter[str] = Counter()
        audit_rows: list[dict[str, Any]] = []

        for message in _iter_history_messages(source_path, limit=limit):
            rows_read += 1
            message = _normalize_history_message(message)
            if self.settings.webex_room_district and not message.get("roomDistrict"):
                message = {**message, "roomDistrict": self.settings.webex_room_district}
            message_id = message.get("id")
            if not message_id:
                skipped_missing_id += 1
                audit_rows.append(_replay_audit_row(message, status="skipped_missing_id"))
                continue
            inserted = self.db.insert_webex_message(message)
            if not inserted and not reprocess_existing:
                skipped_existing += 1
                audit_rows.append(_replay_audit_row(message, status="skipped_existing"))
                continue
            if inserted:
                new_messages += 1

            event = parse_webex_message(message, districts=self.settings.pilot_districts)
            if event is None:
                self.db.mark_message_processed(str(message_id))
                skipped_unparsed += 1
                audit_rows.append(_replay_audit_row(message, status="skipped_unparsed"))
                continue

            parsed_events += 1
            self.db.upsert_event(event)
            match_result = matcher.match(event)
            prediction = predictor.predict(event, match_result)
            self.db.insert_prediction(event.event_id, prediction, match_result)
            predictions += 1
            match_level_counts[match_result.match_level or "<none>"] += 1
            risk_level_counts[prediction.risk_level] += 1
            if match_result.matches:
                affected_events += 1
                affected_customers_total += len(match_result.matches)

            record_status = ""
            if capture_notifications:
                payload = build_notification_payload(
                    event,
                    match_result,
                    prediction,
                    mode="shadow",
                )
                record = NotificationRecord(payload=payload, status="REPLAY_CAPTURED")
                self.db.insert_notification(event.event_id, None, "shadow", record)
                notifications_captured += 1
                notification_status[record.status] += 1
                record_status = record.status

            self.db.mark_message_processed(str(message_id))
            audit_rows.append(
                _replay_audit_row(
                    message,
                    status="processed",
                    event=event,
                    match_level=match_result.match_level or "",
                    match_confidence=match_result.match_confidence,
                    affected_count=len(match_result.matches),
                    risk_level=prediction.risk_level,
                    q50=prediction.etr_minutes_p50,
                    q10=prediction.q10,
                    q90=prediction.q90,
                    notification_status=record_status,
                )
            )

        audit_path = self.settings.resolve(audit_output) if audit_output else None
        if audit_path:
            _write_replay_audit(audit_path, audit_rows)

        return WebexHistoryReplayResult(
            source=str(source_path),
            rows_read=rows_read,
            new_messages=new_messages,
            parsed_events=parsed_events,
            predictions=predictions,
            notifications_captured=notifications_captured,
            skipped_existing=skipped_existing,
            skipped_missing_id=skipped_missing_id,
            skipped_unparsed=skipped_unparsed,
            affected_events=affected_events,
            affected_customers_total=affected_customers_total,
            match_level_counts=dict(sorted(match_level_counts.items())),
            risk_level_counts=dict(sorted(risk_level_counts.items())),
            notification_status=dict(sorted(notification_status.items())),
            audit_output=str(audit_path) if audit_path else None,
        )

    def poll_loop(
        self,
        interval_seconds: int = 60,
        max_messages: int = 50,
        iterations: int | None = None,
    ) -> PollLoopResult:
        totals = {
            "iterations": 0,
            "fetched": 0,
            "new_messages": 0,
            "parsed_events": 0,
            "notifications": 0,
            "skipped": 0,
        }
        while iterations is None or totals["iterations"] < iterations:
            result = self.poll_once(max_messages=max_messages)
            totals["iterations"] += 1
            totals["fetched"] += result.fetched
            totals["new_messages"] += result.new_messages
            totals["parsed_events"] += result.parsed_events
            totals["notifications"] += result.notifications
            totals["skipped"] += result.skipped
            if iterations is not None and totals["iterations"] >= iterations:
                break
            time.sleep(interval_seconds)
        return PollLoopResult(**totals)

    def _webex_client(self) -> Any:
        if self.webex_client is not None:
            return self.webex_client
        if self.settings.webex_auth_mode == "oauth":
            if not self.settings.webex_client_id or not self.settings.webex_client_secret:
                raise RuntimeError("WEBEX_CLIENT_ID and WEBEX_CLIENT_SECRET are required for OAuth polling")
            if not self.settings.webex_room_id:
                raise RuntimeError("WEBEX_ROOM_ID is required for OAuth polling")
            token_manager = WebexOAuthTokenManager(
                client_id=self.settings.webex_client_id,
                client_secret=<REDACTED_SECRET>
                token_path=self.settings.resolve(self.settings.webex_token_path),
                api_base=self.settings.webex_api_base,
            )
            self.webex_client = WebexClient(
                room_id=self.settings.webex_room_id,
                api_base=self.settings.webex_api_base,
                require_mention=False,
                token_provider=token_manager.access_token,
            )
            return self.webex_client
        if not self.settings.webex_bot_token or not self.settings.webex_room_id:
            raise RuntimeError("WEBEX_BOT_TOKEN and WEBEX_ROOM_ID are required for polling")
        self.webex_client = WebexClient(
            bot_token=self.settings.webex_bot_token,
            room_id=self.settings.webex_room_id,
            api_base=self.settings.webex_api_base,
            require_mention=self.settings.webex_require_mention,
        )
        return self.webex_client


def _iter_history_messages(path: Path, limit: int | None = None):
    if not path.exists():
        raise FileNotFoundError(f"Webex history source does not exist: {path}")
    count = 0
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if limit is not None and count >= limit:
                    break
                count += 1
                yield dict(row)
        return
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if limit is not None and count >= limit:
                break
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
            count += 1
            yield message


def _normalize_history_message(message: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(message)
    if normalized.get("room_id") and not normalized.get("roomId"):
        normalized["roomId"] = normalized["room_id"]
    if normalized.get("parent_id") and not normalized.get("parentId"):
        normalized["parentId"] = normalized["parent_id"]
    if not normalized.get("text") and normalized.get("markdown"):
        normalized["text"] = normalized["markdown"]
    return normalized


def _replay_audit_row(
    message: dict[str, Any],
    status: str,
    event: Any | None = None,
    match_level: str = "",
    match_confidence: float | str = "",
    affected_count: int | str = "",
    risk_level: str = "",
    q50: float | str = "",
    q10: float | str = "",
    q90: float | str = "",
    notification_status: str = "",
) -> dict[str, Any]:
    return {
        "webex_message_id": message.get("id") or "",
        "message_created": message.get("created") or "",
        "status": status,
        "event_id": event.event_id if event else "",
        "event_time": event.event_time if event else "",
        "district": event.district if event else "",
        "device_type": event.outage_device.device_type if event else "",
        "device_id": event.outage_device.device_id if event else "",
        "feeder": event.outage_device.feeder if event else "",
        "event_number": (event.parsed_fields or {}).get("event_number", "") if event else "",
        "event_number_missing_reason": (event.parsed_fields or {}).get("event_number_missing_reason", "") if event else "",
        "match_level": match_level,
        "match_confidence": match_confidence,
        "affected_count": affected_count,
        "risk_level": risk_level,
        "etr_minutes_p50": q50,
        "q10": q10,
        "q90": q90,
        "notification_status": notification_status,
    }


def _write_replay_audit(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "webex_message_id",
        "message_created",
        "status",
        "event_id",
        "event_time",
        "district",
        "device_type",
        "device_id",
        "feeder",
        "event_number",
        "event_number_missing_reason",
        "match_level",
        "match_confidence",
        "affected_count",
        "risk_level",
        "etr_minutes_p50",
        "q10",
        "q90",
        "notification_status",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
