from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any


BASE_COLUMNS = [
    "id",
    "created",
    "updated",
    "parent_id",
    "text",
    "markdown",
    "files_count",
]
ROOM_COLUMNS = ["room_id"]
ACTOR_COLUMNS = ["person_id", "person_email", "person_display_name"]
RAW_COLUMNS = ["raw_json"]


def export_webex_room_history(
    client: Any,
    output_jsonl: str | Path,
    output_csv: str | Path | None = None,
    sample_output: str | Path | None = None,
    max_messages: int = 500,
    page_size: int = 100,
    before: str | None = None,
    after: str | None = None,
    include_room_id: bool = False,
    include_actor: bool = False,
    include_raw: bool = False,
    sleep_seconds: float = 0.2,
) -> dict[str, Any]:
    if max_messages < 1:
        raise ValueError("max_messages must be >= 1")
    if page_size < 1:
        raise ValueError("page_size must be >= 1")

    after_dt = _parse_timestamp(after) if after else None
    output_jsonl = Path(output_jsonl)
    output_csv = Path(output_csv) if output_csv else None
    sample_output = Path(sample_output) if sample_output else None

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    before_message: str | None = None
    reached_after_boundary = False
    api_calls = 0

    while len(records) < max_messages and not reached_after_boundary:
        limit = min(page_size, max_messages - len(records))
        page = client.list_messages(
            max_items=limit,
            before=before if before_message is None else None,
            before_message=before_message,
        )
        api_calls += 1
        if not page:
            break

        next_before_message = None
        for message in page:
            message_id = str(message.get("id") or "")
            if message_id:
                next_before_message = message_id
            if not message_id or message_id in seen_ids:
                continue
            created_dt = _parse_timestamp(message.get("created"))
            if after_dt and created_dt and created_dt < after_dt:
                reached_after_boundary = True
                continue
            seen_ids.add(message_id)
            records.append(
                _sanitize_message(
                    message,
                    include_room_id=include_room_id,
                    include_actor=include_actor,
                    include_raw=include_raw,
                )
            )
            if len(records) >= max_messages:
                break

        if not next_before_message or next_before_message == before_message:
            break
        before_message = next_before_message
        if len(records) < max_messages and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    if output_csv:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        columns = _columns(include_room_id=include_room_id, include_actor=include_actor, include_raw=include_raw)
        with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)

    if sample_output:
        sample_output.parent.mkdir(parents=True, exist_ok=True)
        with sample_output.open("w", encoding="utf-8") as handle:
            for record in records:
                sample = {
                    "id": record["id"],
                    "created": record.get("created"),
                    "text": record.get("text"),
                    "markdown": record.get("markdown"),
                }
                handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "api_calls": api_calls,
        "exported": len(records),
        "output_jsonl": str(output_jsonl),
        "output_csv": str(output_csv) if output_csv else None,
        "sample_output": str(sample_output) if sample_output else None,
        "include_room_id": include_room_id,
        "include_actor": include_actor,
        "include_raw": include_raw,
        "after_boundary_reached": reached_after_boundary,
    }


def _columns(include_room_id: bool, include_actor: bool, include_raw: bool) -> list[str]:
    columns = list(BASE_COLUMNS)
    if include_room_id:
        columns.extend(ROOM_COLUMNS)
    if include_actor:
        columns.extend(ACTOR_COLUMNS)
    if include_raw:
        columns.extend(RAW_COLUMNS)
    return columns


def _sanitize_message(
    message: dict[str, Any],
    include_room_id: bool,
    include_actor: bool,
    include_raw: bool,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": message.get("id"),
        "created": message.get("created"),
        "updated": message.get("updated"),
        "parent_id": message.get("parentId"),
        "text": message.get("text"),
        "markdown": message.get("markdown"),
        "files_count": len(message.get("files") or []),
    }
    if include_room_id:
        record["room_id"] = message.get("roomId")
    if include_actor:
        record["person_id"] = message.get("personId")
        record["person_email"] = message.get("personEmail")
        record["person_display_name"] = message.get("personDisplayName")
    if include_raw:
        record["raw_json"] = json.dumps(message, ensure_ascii=False, sort_keys=True)
    return record


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
