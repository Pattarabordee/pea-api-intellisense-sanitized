from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from .schemas import CustomerAsset, MatchResult, NotificationRecord, OutageEvent, Prediction, utc_now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS webex_messages (
    id TEXT PRIMARY KEY,
    room_id TEXT,
    created TEXT,
    text TEXT,
    raw_json TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS outage_events (
    event_id TEXT PRIMARY KEY,
    webex_message_id TEXT UNIQUE,
    room_id TEXT,
    event_time TEXT,
    district TEXT,
    site TEXT,
    device_type TEXT,
    device_id TEXT,
    feeder TEXT,
    raw_text TEXT,
    parsed_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customer_assets (
    peano TEXT PRIMARY KEY,
    customer TEXT NOT NULL,
    feeder TEXT,
    meter_location TEXT,
    transformer_id TEXT,
    transformer_peano TEXT,
    recloser_ids TEXT NOT NULL,
    switch_ids TEXT NOT NULL,
    cb_ids TEXT NOT NULL,
    trace_status TEXT,
    confidence_eligible INTEGER NOT NULL,
    raw_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    etr_minutes_p50 REAL NOT NULL,
    q25 REAL NOT NULL,
    q75 REAL NOT NULL,
    q10 REAL NOT NULL,
    q90 REAL NOT NULL,
    risk_level TEXT NOT NULL,
    match_confidence REAL NOT NULL,
    affected_count INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    endpoint_url TEXT,
    mode TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    status_code INTEGER,
    response_text TEXT,
    sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_runs (
    model_version TEXT PRIMARY KEY,
    trained_at TEXT NOT NULL,
    estimator TEXT NOT NULL,
    status TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    artifact_path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ais_inbound_requests (
    request_id TEXT PRIMARY KEY,
    received_at TEXT NOT NULL,
    peano_hash TEXT,
    peano_last4 TEXT,
    detected_at TEXT,
    province TEXT,
    district TEXT,
    subdistrict TEXT,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    callback_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ais_inbound_callbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    callback_url TEXT,
    mode TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    status_code INTEGER,
    response_text TEXT,
    sent_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ais_inbound_callbacks_request_id_id
ON ais_inbound_callbacks (request_id, id);
"""


class RuntimeDb:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def session(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.session() as conn:
            conn.executescript(SCHEMA)

    def insert_webex_message(self, message: dict[str, Any]) -> bool:
        raw_json = json.dumps(message, ensure_ascii=False, sort_keys=True)
        text = message.get("text") or message.get("markdown") or ""
        with self.session() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO webex_messages (id, room_id, created, text, raw_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message.get("id"), message.get("roomId"), message.get("created"), text, raw_json),
            )
            return cur.rowcount == 1

    def mark_message_processed(self, message_id: str) -> None:
        with self.session() as conn:
            conn.execute(
                "UPDATE webex_messages SET processed_at = ? WHERE id = ?",
                (utc_now_iso(), message_id),
            )

    def upsert_event(self, event: OutageEvent) -> None:
        data = event.asdict()
        with self.session() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO outage_events (
                    event_id, webex_message_id, room_id, event_time, district, site,
                    device_type, device_id, feeder, raw_text, parsed_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.webex_message_id,
                    event.room_id,
                    event.event_time,
                    event.district,
                    event.site,
                    event.outage_device.device_type,
                    event.outage_device.device_id,
                    event.outage_device.feeder,
                    event.raw_text,
                    json.dumps(data, ensure_ascii=False, sort_keys=True),
                    utc_now_iso(),
                ),
            )

    def upsert_customer_assets(self, assets: Iterable[CustomerAsset]) -> int:
        rows = []
        now = utc_now_iso()
        for asset in assets:
            raw = asset.asdict()
            rows.append(
                (
                    asset.peano,
                    asset.customer,
                    asset.feeder,
                    asset.meter_location,
                    asset.transformer_id,
                    asset.transformer_peano,
                    json.dumps(asset.recloser_ids, ensure_ascii=False),
                    json.dumps(asset.switch_ids, ensure_ascii=False),
                    json.dumps(asset.cb_ids, ensure_ascii=False),
                    asset.trace_status,
                    1 if asset.confidence_eligible else 0,
                    json.dumps(raw, ensure_ascii=False, sort_keys=True),
                    now,
                )
            )
        with self.session() as conn:
            conn.executemany(
                """
                INSERT INTO customer_assets (
                    peano, customer, feeder, meter_location, transformer_id, transformer_peano,
                    recloser_ids, switch_ids, cb_ids, trace_status, confidence_eligible,
                    raw_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(peano) DO UPDATE SET
                    customer=excluded.customer,
                    feeder=excluded.feeder,
                    meter_location=excluded.meter_location,
                    transformer_id=excluded.transformer_id,
                    transformer_peano=excluded.transformer_peano,
                    recloser_ids=excluded.recloser_ids,
                    switch_ids=excluded.switch_ids,
                    cb_ids=excluded.cb_ids,
                    trace_status=excluded.trace_status,
                    confidence_eligible=excluded.confidence_eligible,
                    raw_json=excluded.raw_json,
                    updated_at=excluded.updated_at
                """,
                rows,
            )
        return len(rows)

    def load_customer_assets(self) -> list[CustomerAsset]:
        with self.session() as conn:
            rows = conn.execute("SELECT * FROM customer_assets").fetchall()
        assets = []
        for row in rows:
            assets.append(
                CustomerAsset(
                    peano=row["peano"],
                    customer=row["customer"],
                    feeder=row["feeder"],
                    meter_location=row["meter_location"],
                    transformer_id=row["transformer_id"],
                    transformer_peano=row["transformer_peano"],
                    recloser_ids=tuple(json.loads(row["recloser_ids"] or "[]")),
                    switch_ids=tuple(json.loads(row["switch_ids"] or "[]")),
                    cb_ids=tuple(json.loads(row["cb_ids"] or "[]")),
                    trace_status=row["trace_status"],
                    confidence_eligible=bool(row["confidence_eligible"]),
                )
            )
        return assets

    def insert_prediction(
        self,
        event_id: str,
        prediction: Prediction,
        match_result: MatchResult,
    ) -> None:
        with self.session() as conn:
            conn.execute(
                """
                INSERT INTO predictions (
                    event_id, model_version, etr_minutes_p50, q25, q75, q10, q90,
                    risk_level, match_confidence, affected_count, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    prediction.model_version,
                    prediction.etr_minutes_p50,
                    prediction.q25,
                    prediction.q75,
                    prediction.q10,
                    prediction.q90,
                    prediction.risk_level,
                    match_result.match_confidence,
                    len(match_result.matches),
                    utc_now_iso(),
                ),
            )

    def insert_notification(
        self,
        event_id: str,
        endpoint_url: str | None,
        mode: str,
        record: NotificationRecord,
    ) -> None:
        with self.session() as conn:
            conn.execute(
                """
                INSERT INTO notifications (
                    event_id, endpoint_url, mode, payload_json, status,
                    status_code, response_text, sent_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    endpoint_url,
                    mode,
                    json.dumps(record.payload, ensure_ascii=False, sort_keys=True),
                    record.status,
                    record.status_code,
                    record.response_text,
                    utc_now_iso(),
                ),
            )

    def notification_exists(self, event_id: str, mode: str | None = None) -> bool:
        query = "SELECT 1 FROM notifications WHERE event_id = ?"
        params: tuple[Any, ...]
        if mode is None:
            params = (event_id,)
        else:
            query += " AND mode = ?"
            params = (event_id, mode)
        query += " LIMIT 1"
        with self.session() as conn:
            return conn.execute(query, params).fetchone() is not None

    def insert_model_run(
        self,
        model_version: str,
        estimator: str,
        status: str,
        metrics: dict[str, Any],
        artifact_path: str | Path,
    ) -> None:
        with self.session() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO model_runs (
                    model_version, trained_at, estimator, status, metrics_json, artifact_path
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    model_version,
                    utc_now_iso(),
                    estimator,
                    status,
                    json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                    str(artifact_path),
                ),
            )
