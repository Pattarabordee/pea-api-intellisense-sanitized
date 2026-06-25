from __future__ import annotations

import csv
from pathlib import Path
import shutil
from typing import Any

from .config import Settings, load_env_file
from .db import RuntimeDb


REQUIRED_BOT_KEYS = ("WEBEX_BOT_TOKEN", "WEBEX_ROOM_ID")
REQUIRED_OAUTH_KEYS = (
    "WEBEX_CLIENT_ID",
    "WEBEX_CLIENT_SECRET",
    "WEBEX_REDIRECT_URI",
    "WEBEX_SCOPES",
    "WEBEX_ROOM_ID",
)


def setup_env(example_path: str | Path = ".env.example", env_path: str | Path = ".env", force: bool = False) -> dict:
    example = Path(example_path)
    target = Path(env_path)
    if not example.exists():
        return {"status": "missing_example", "example": str(example)}
    if target.exists() and not force:
        return {"status": "exists", "env": str(target), "changed": False}
    shutil.copyfile(example, target)
    return {"status": "created" if not force else "overwritten", "env": str(target), "changed": True}


def validate_env(settings: Settings, env_path: str | Path = ".env") -> dict[str, Any]:
    load_env_file(env_path)
    missing = []
    warnings = []
    auth_mode = settings.webex_auth_mode
    token_path = settings.resolve(settings.webex_token_path)
    token_exists = token_path.exists()
    if auth_mode == "oauth":
        values = {
            "WEBEX_CLIENT_ID": settings.webex_client_id,
            "WEBEX_CLIENT_SECRET": settings.webex_client_secret,
            "WEBEX_REDIRECT_URI": settings.webex_redirect_uri,
            "WEBEX_SCOPES": " ".join(settings.webex_scopes),
            "WEBEX_ROOM_ID": settings.webex_room_id,
        }
        for key in REQUIRED_OAUTH_KEYS:
            if not values.get(key):
                missing.append(key)
        if not token_exists:
            missing.append("WEBEX_TOKEN_PATH")
    elif auth_mode == "bot":
        values = {
            "WEBEX_BOT_TOKEN": settings.webex_bot_token,
            "WEBEX_ROOM_ID": settings.webex_room_id,
        }
        for key in REQUIRED_BOT_KEYS:
            if not values.get(key):
                missing.append(key)
    else:
        missing.append("WEBEX_AUTH_MODE")
        warnings.append("WEBEX_AUTH_MODE must be either 'bot' or 'oauth'")
    if settings.notification_mode != "shadow":
        warnings.append("AIS_NOTIFICATION_MODE must remain 'shadow' for this MVP notifier")
    if settings.line_capture_mode != "shadow":
        warnings.append("LINE_CAPTURE_MODE must remain 'shadow'")
    if settings.line_channel_secret and not settings.line_allowed_group_ids and not settings.line_allowed_chat_hashes:
        warnings.append("LINE_ALLOWED_GROUP_IDS and LINE_ALLOWED_CHAT_HASHES are empty; LINE webhook capture will reject all groups")
    if not settings.mock_webhook_url:
        warnings.append("AIS_MOCK_WEBHOOK_URL is empty; payloads will be stored as SKIPPED_NO_ENDPOINT")
    planned_outage_path = settings.resolve(settings.planned_outage_file)
    if not planned_outage_path.exists():
        warnings.append(f"AIS_PLANNED_OUTAGE_CSV does not exist: {planned_outage_path}")
    return {
        "ok": not missing and settings.notification_mode == "shadow",
        "missing": missing,
        "warnings": warnings,
        "webex_auth_mode": auth_mode,
        "webex_room_district_configured": bool(settings.webex_room_district),
        "webex_token": {
            "path": str(token_path),
            "exists": token_exists,
        },
        "line_capture_mode": settings.line_capture_mode,
        "line_channel_secret_configured": bool(settings.line_channel_secret),
        "line_allowed_group_count": len(settings.line_allowed_group_ids),
        "line_allowed_chat_hash_count": len(settings.line_allowed_chat_hashes),
        "notification_mode": settings.notification_mode,
        "mock_webhook_configured": bool(settings.mock_webhook_url),
        "db_path": str(settings.resolve(settings.db_path)),
        "registry_path": str(settings.resolve(settings.registry_path)),
        "model_path": str(settings.resolve(settings.model_path)),
        "planned_outage_path": str(planned_outage_path),
        "planned_notice_min_days": settings.planned_notice_min_days,
        "planned_require_asset_match": settings.planned_require_asset_match,
    }


def export_no_meter_backlog(db: RuntimeDb, output_path: str | Path) -> dict[str, Any]:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with db.session() as conn:
        rows = conn.execute(
            """
            SELECT peano, customer, feeder, meter_location, trace_status, raw_json, updated_at
            FROM customer_assets
            WHERE trace_status = 'NO_METER' OR confidence_eligible = 0
            ORDER BY peano
            """
        ).fetchall()
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["PEANO", "customer", "feeder", "meter_location", "trace_status", "updated_at"])
        for row in rows:
            writer.writerow(
                [
                    row["peano"],
                    row["customer"],
                    row["feeder"],
                    row["meter_location"],
                    row["trace_status"],
                    row["updated_at"],
                ]
            )
    return {"output": str(output), "rows": len(rows)}
