from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


OUTPUT_COLUMNS = (
    "request_ref",
    "event_time",
    "meter_ref",
    "evidence_status",
    "evidence_count",
    "use_for_training_target",
    "production_send",
)
ALLOWED_STATUSES = {
    "pea_evidence_supported",
    "pea_evidence_not_found",
    "context_conflict",
    "insufficient_evidence",
}


def run_local_evidence_lane(
    *,
    base_url: str,
    snapshot_csvs: list[str | Path],
    output_csv: str | Path,
    report_md: str | Path,
    api_key: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    key = str(api_key or os.environ.get("AIS_INBOUND_API_KEY") or "").strip()
    if not key:
        raise ValueError("AIS_INBOUND_API_KEY is required")
    url = base_url.rstrip("/") + f"/api/v1/ais/outage-verifications?view=operator&limit={max(1, min(limit, 200))}"
    request = Request(url, method="GET", headers={"X-API-Key": key, "Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return build_local_evidence_report(
        payload.get("items") or [],
        snapshot_csvs=snapshot_csvs,
        output_csv=output_csv,
        report_md=report_md,
    )


def build_local_evidence_report(
    operator_items: list[dict[str, Any]],
    *,
    snapshot_csvs: list[str | Path],
    output_csv: str | Path,
    report_md: str | Path,
) -> dict[str, Any]:
    evidence = _load_evidence(snapshot_csvs)
    rows: list[dict[str, Any]] = []
    for item in operator_items:
        request_ref = str(item.get("request_ref") or "").strip()
        meter_ref = str((item.get("meter") or {}).get("hash") or "").strip()
        event_time = _parse_time(item.get("detected_at") or item.get("received_at"))
        candidates = [row for row in evidence if row["meter_ref"] == meter_ref]
        pre_event = [row for row in candidates if event_time and row["evidence_time"] and row["evidence_time"] <= event_time]
        if not request_ref or not meter_ref or not event_time:
            status = "insufficient_evidence"
        elif any(row["status"] == "context_conflict" for row in pre_event):
            status = "context_conflict"
        elif any(row["status"] == "pea_evidence_supported" for row in pre_event):
            status = "pea_evidence_supported"
        elif candidates and not pre_event:
            status = "insufficient_evidence"
        else:
            status = "pea_evidence_not_found"
        rows.append(
            {
                "request_ref": request_ref,
                "event_time": _format_time(event_time) if event_time else "",
                "meter_ref": meter_ref,
                "evidence_status": status,
                "evidence_count": len(pre_event),
                "use_for_training_target": "FALSE",
                "production_send": "blocked",
            }
        )
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    counts = {status: sum(1 for row in rows if row["evidence_status"] == status) for status in sorted(ALLOWED_STATUSES)}
    report = Path(report_md)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "# Local PEA Evidence Lane\n\n"
        "- Mode: one-shot, read-only cloud GET\n"
        "- Evidence role: context only\n"
        "- Training target: disabled\n"
        "- Production send: blocked\n\n"
        + "\n".join(f"- `{status}`: {count}" for status, count in counts.items())
        + "\n",
        encoding="utf-8",
    )
    return {
        "requests": len(rows),
        "status_counts": counts,
        "output_csv": str(output),
        "report_md": str(report),
        "production_send": "blocked",
    }


def _load_evidence(paths: list[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists() or path.suffix.lower() != ".csv":
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for source in csv.DictReader(handle):
                status = str(source.get("evidence_status") or source.get("status") or "").strip()
                rows.append(
                    {
                        "meter_ref": str(source.get("meter_ref") or source.get("meter_hash") or "").strip(),
                        "evidence_time": _parse_time(source.get("evidence_time") or source.get("event_time")),
                        "status": status if status in ALLOWED_STATUSES else "insufficient_evidence",
                    }
                )
    return rows


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
