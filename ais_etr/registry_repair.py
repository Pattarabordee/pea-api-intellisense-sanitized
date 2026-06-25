from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sqlite3
from typing import Any


COLUMNS = [
    "priority_rank",
    "repair_category",
    "device_type",
    "device_id",
    "feeder",
    "district",
    "event_count",
    "first_event_time",
    "last_event_time",
    "risk_level_counts",
    "notification_status_counts",
    "registry_total_assets_on_feeder",
    "registry_confident_assets_on_feeder",
    "registry_no_meter_assets_on_feeder",
    "registry_device_asset_count",
    "expected_registry_field",
    "recommended_action",
    "sample_webex_message_ids",
]


def build_no_match_repair_candidates(
    db_path: str | Path,
    output_csv: str | Path,
    min_events: int = 1,
    max_sample_ids: int = 5,
) -> dict[str, Any]:
    events = _load_no_match_events(db_path)
    assets = _load_registry_assets(db_path)
    registry = _registry_index(assets)
    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for event in events:
        key = (
            event.get("device_type") or "",
            event.get("device_id") or "",
            event.get("feeder") or "",
            event.get("district") or "",
        )
        group = groups.setdefault(
            key,
            {
                "device_type": key[0],
                "device_id": key[1],
                "feeder": key[2],
                "district": key[3],
                "event_times": [],
                "risk_levels": Counter(),
                "notification_status": Counter(),
                "sample_ids": [],
            },
        )
        if event.get("event_time"):
            group["event_times"].append(str(event["event_time"]))
        group["risk_levels"][event.get("risk_level") or "<missing>"] += 1
        group["notification_status"][event.get("notification_status") or "<missing>"] += 1
        if event.get("webex_message_id") and len(group["sample_ids"]) < max_sample_ids:
            group["sample_ids"].append(str(event["webex_message_id"]))

    rows = []
    for group in groups.values():
        event_count = sum(group["risk_levels"].values())
        if event_count < min_events:
            continue
        feeder = group["feeder"]
        device_id = group["device_id"]
        device_type = group["device_type"]
        feeder_stats = registry["by_feeder"].get(feeder, _empty_feeder_stats())
        device_count = registry["by_device"].get(device_id, 0) if device_id else 0
        category, action = _repair_guidance(
            device_id=device_id,
            device_type=device_type,
            feeder=feeder,
            feeder_stats=feeder_stats,
            device_count=device_count,
        )
        event_times = sorted(group["event_times"])
        rows.append(
            {
                "repair_category": category,
                "device_type": device_type or "Unknown",
                "device_id": device_id,
                "feeder": feeder,
                "district": group["district"],
                "event_count": event_count,
                "first_event_time": event_times[0] if event_times else "",
                "last_event_time": event_times[-1] if event_times else "",
                "risk_level_counts": _json_counts(group["risk_levels"]),
                "notification_status_counts": _json_counts(group["notification_status"]),
                "registry_total_assets_on_feeder": feeder_stats["total"],
                "registry_confident_assets_on_feeder": feeder_stats["eligible"],
                "registry_no_meter_assets_on_feeder": feeder_stats["no_meter"],
                "registry_device_asset_count": device_count,
                "expected_registry_field": _expected_registry_field(device_type),
                "recommended_action": action,
                "sample_webex_message_ids": ";".join(group["sample_ids"]),
            }
        )

    rows.sort(
        key=lambda row: (
            -int(row["event_count"]),
            -int(row["registry_confident_assets_on_feeder"]),
            row["device_type"],
            row["device_id"],
            row["feeder"],
        )
    )
    for rank, row in enumerate(rows, 1):
        row["priority_rank"] = rank

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    categories = Counter(row["repair_category"] for row in rows)
    top_feeders = Counter()
    for row in rows:
        top_feeders[row["feeder"] or "<missing>"] += int(row["event_count"])
    return {
        "output_csv": str(output),
        "no_match_events": len(events),
        "candidate_rows": len(rows),
        "min_events": min_events,
        "repair_category_counts": dict(sorted(categories.items())),
        "top_feeders": dict(top_feeders.most_common(10)),
    }


def _load_no_match_events(db_path: str | Path) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        query = """
            WITH latest_predictions AS (
                SELECT p.*
                FROM predictions p
                JOIN (
                    SELECT event_id, MAX(id) AS max_id
                    FROM predictions
                    GROUP BY event_id
                ) latest ON latest.max_id = p.id
            ),
            latest_notifications AS (
                SELECT n.*
                FROM notifications n
                JOIN (
                    SELECT event_id, MAX(id) AS max_id
                    FROM notifications
                    GROUP BY event_id
                ) latest ON latest.max_id = n.id
            )
            SELECT
                e.event_id,
                e.webex_message_id,
                e.event_time,
                e.district,
                e.device_type,
                e.device_id,
                e.feeder,
                p.risk_level,
                p.affected_count,
                n.status AS notification_status
            FROM outage_events e
            JOIN latest_predictions p ON p.event_id = e.event_id
            LEFT JOIN latest_notifications n ON n.event_id = e.event_id
            WHERE COALESCE(p.affected_count, 0) = 0
              AND e.webex_message_id IS NOT NULL
            ORDER BY COALESCE(e.event_time, ''), e.event_id
        """
        return [dict(row) for row in conn.execute(query).fetchall()]
    finally:
        conn.close()


def _load_registry_assets(db_path: str | Path) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                feeder,
                transformer_id,
                transformer_peano,
                recloser_ids,
                switch_ids,
                cb_ids,
                trace_status,
                confidence_eligible
            FROM customer_assets
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _registry_index(assets: list[dict[str, Any]]) -> dict[str, Any]:
    by_feeder: dict[str, dict[str, int]] = defaultdict(_empty_feeder_stats)
    by_device: Counter[str] = Counter()
    for asset in assets:
        feeder = str(asset.get("feeder") or "")
        stats = by_feeder[feeder]
        stats["total"] += 1
        if int(asset.get("confidence_eligible") or 0):
            stats["eligible"] += 1
        if str(asset.get("trace_status") or "").upper() == "NO_METER":
            stats["no_meter"] += 1
        for device in _asset_devices(asset):
            by_device[device] += 1
    return {"by_feeder": by_feeder, "by_device": by_device}


def _asset_devices(asset: dict[str, Any]) -> set[str]:
    devices = {
        str(asset.get("transformer_id") or ""),
        str(asset.get("transformer_peano") or ""),
    }
    for column in ("recloser_ids", "switch_ids", "cb_ids"):
        try:
            values = json.loads(asset.get(column) or "[]")
        except Exception:
            values = []
        devices.update(str(value) for value in values if value)
    return {device for device in devices if device}


def _empty_feeder_stats() -> dict[str, int]:
    return {"total": 0, "eligible": 0, "no_meter": 0}


def _repair_guidance(
    device_id: str,
    device_type: str,
    feeder: str,
    feeder_stats: dict[str, int],
    device_count: int,
) -> tuple[str, str]:
    if not device_id:
        return (
            "parser_device_missing",
            "Review the Webex text and add a parser pattern only if the message contains a real protection device id.",
        )
    if not feeder:
        return (
            "parser_feeder_missing",
            "Review device normalization and feeder extraction before changing registry topology.",
        )
    if feeder_stats["total"] == 0:
        return (
            "outside_registry_or_missing_feeder_trace",
            "Confirm whether this feeder has AIS pilot assets. If yes, repair upstream_result trace rows before enabling confident matching.",
        )
    if feeder_stats["eligible"] == 0:
        return (
            "feeder_has_no_confident_assets",
            "Repair NO_METER or incomplete trace rows on this feeder before using the event for confident customer impact.",
        )
    if device_count == 0:
        return (
            "protection_device_not_in_registry_trace",
            f"Verify whether AIS assets on feeder {feeder} are downstream of {device_id}; if confirmed, update the {_expected_registry_field(device_type)} field in the traced registry.",
        )
    return (
        "matching_rule_review",
        "Device exists in registry but did not match this event; review normalization, device type precedence, and duplicate asset trace values.",
    )


def _expected_registry_field(device_type: str) -> str:
    normalized = (device_type or "").strip().lower()
    if normalized == "cb":
        return "cb_ids"
    if normalized == "recloser":
        return "recloser_ids"
    if normalized == "switch":
        return "switch_ids"
    if normalized == "transformer":
        return "transformer_id/transformer_peano"
    return "unknown_protection_field"


def _json_counts(counter: Counter[str]) -> str:
    return json.dumps(dict(sorted(counter.items())), ensure_ascii=False, sort_keys=True)
