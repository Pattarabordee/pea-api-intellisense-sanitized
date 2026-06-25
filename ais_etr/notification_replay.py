from __future__ import annotations

import json
from typing import Any

from .db import RuntimeDb
from .notifier import ShadowNotifier


DEFAULT_REPLAY_STATUSES = ("ERROR", "HTTP_ERROR", "SKIPPED_NO_ENDPOINT")


def replay_failed_shadow_notifications(
    db: RuntimeDb,
    endpoint_url: str | None,
    statuses: tuple[str, ...] = DEFAULT_REPLAY_STATUSES,
    limit: int | None = None,
) -> dict[str, Any]:
    if not endpoint_url:
        raise ValueError("A mock webhook endpoint URL is required for notification replay")
    rows = _latest_failed_shadow_rows(db, statuses, limit)
    notifier = ShadowNotifier(endpoint_url)
    result_status: dict[str, int] = {}
    skipped_invalid = 0
    replayed = 0
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            skipped_invalid += 1
            continue
        if not isinstance(payload, dict) or payload.get("mode") != "shadow":
            skipped_invalid += 1
            continue
        record = notifier.send(payload)
        db.insert_notification(row["event_id"], endpoint_url, "shadow", record)
        result_status[record.status] = result_status.get(record.status, 0) + 1
        replayed += 1
    return {
        "candidates": len(rows),
        "replayed": replayed,
        "skipped_invalid_payload": skipped_invalid,
        "endpoint_url": endpoint_url,
        "source_statuses": list(statuses),
        "result_status": result_status,
    }


def _latest_failed_shadow_rows(
    db: RuntimeDb,
    statuses: tuple[str, ...],
    limit: int | None,
) -> list[Any]:
    placeholders = ",".join("?" for _ in statuses)
    query = f"""
        WITH latest_notifications AS (
            SELECT n.*
            FROM notifications n
            JOIN (
                SELECT event_id, MAX(id) AS max_id
                FROM notifications
                WHERE mode = 'shadow'
                GROUP BY event_id
            ) latest ON latest.max_id = n.id
        )
        SELECT *
        FROM latest_notifications
        WHERE mode = 'shadow'
          AND status IN ({placeholders})
        ORDER BY id
    """
    params: list[Any] = list(statuses)
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    with db.session() as conn:
        return list(conn.execute(query, params).fetchall())
