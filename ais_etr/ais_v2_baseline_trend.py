from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .ais_v2_baseline_evaluation import _sample_size_status


TREND_COLUMNS = (
    "evaluation_id",
    "registered_at",
    "scorable_independent_incidents",
    "sample_size_status",
    "mae_minutes",
    "mae_delta_minutes",
    "median_absolute_error_minutes",
    "p90_absolute_error_minutes",
    "mean_worst_meter_absolute_error_minutes",
    "green_incidents",
    "high_error_incidents",
    "coverage_status",
    "research_metric_claim_allowed",
    "production_accuracy_claim_allowed",
    "production_send",
)


def build_v2_baseline_trend(
    registry_jsonl: str | Path,
    *,
    output_csv: str | Path,
    report_md: str | Path,
    peacon_md: str | Path,
) -> dict[str, Any]:
    entries = _load_registry(Path(registry_jsonl))
    rows: list[dict[str, Any]] = []
    previous_mae: float | None = None
    for entry in entries:
        incidents = int(entry.get("scorable_independent_incidents") or 0)
        mae = _float_or_none(entry.get("mae_minutes"))
        mae_delta = None if mae is None or previous_mae is None else round(mae - previous_mae, 3)
        rows.append(
            {
                "evaluation_id": str(entry.get("evaluation_id") or ""),
                "registered_at": str(entry.get("registered_at") or ""),
                "scorable_independent_incidents": incidents,
                "sample_size_status": str(entry.get("sample_size_status") or _sample_size_status(incidents)),
                "mae_minutes": mae,
                "mae_delta_minutes": mae_delta,
                "median_absolute_error_minutes": _float_or_none(entry.get("median_absolute_error_minutes")),
                "p90_absolute_error_minutes": _float_or_none(entry.get("p90_absolute_error_minutes")),
                "mean_worst_meter_absolute_error_minutes": _float_or_none(
                    entry.get("mean_worst_meter_absolute_error_minutes")
                ),
                "green_incidents": int(entry.get("green_incidents") or 0),
                "high_error_incidents": int(entry.get("high_error_incidents") or 0),
                "coverage_status": str(entry.get("coverage_status") or "unavailable"),
                "research_metric_claim_allowed": incidents >= 30,
                "production_accuracy_claim_allowed": False,
                "production_send": "blocked",
            }
        )
        if mae is not None:
            previous_mae = mae

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TREND_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    latest = rows[-1] if rows else None
    report = Path(report_md)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(_render_report(rows, latest), encoding="utf-8")

    peacon = Path(peacon_md)
    peacon.parent.mkdir(parents=True, exist_ok=True)
    peacon.write_text(_render_peacon(latest), encoding="utf-8")

    return {
        "registry_entries": len(rows),
        "latest_evaluation_id": latest["evaluation_id"] if latest else "",
        "latest_scorable_independent_incidents": latest["scorable_independent_incidents"] if latest else 0,
        "latest_sample_size_status": latest["sample_size_status"] if latest else "awaiting_first_scorable_incident",
        "latest_mae_minutes": latest["mae_minutes"] if latest else None,
        "research_metric_claim_allowed": bool(latest and latest["research_metric_claim_allowed"]),
        "production_accuracy_claim_allowed": False,
        "production_send": "blocked",
        "output_csv": str(output),
        "report_md": str(report),
        "peacon_md": str(peacon),
    }


def _load_registry(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    unique: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid registry JSON at line {line_number}") from exc
        evaluation_id = str(entry.get("evaluation_id") or "").strip()
        if not evaluation_id:
            raise ValueError(f"missing evaluation_id at line {line_number}")
        if entry.get("production_send") != "blocked":
            raise ValueError(f"registry production_send must remain blocked at line {line_number}")
        unique.setdefault(evaluation_id, entry)
    return sorted(unique.values(), key=lambda row: (str(row.get("registered_at") or ""), str(row.get("evaluation_id") or "")))


def _render_report(rows: list[dict[str, Any]], latest: dict[str, Any] | None) -> str:
    if latest is None:
        return (
            "# Prospective v2 Baseline Trend\n\n"
            "- status: `awaiting_first_registry_entry`\n"
            "- research metric claim allowed: `false`\n"
            "- production accuracy claim allowed: `false`\n"
            "- production_send: `blocked`\n"
        )
    research_allowed = str(bool(latest["research_metric_claim_allowed"])).lower()
    return (
        "# Prospective v2 Baseline Trend\n\n"
        f"- registry entries: `{len(rows)}`\n"
        f"- latest independent incidents: `{latest['scorable_independent_incidents']}`\n"
        f"- sample size status: `{latest['sample_size_status']}`\n"
        f"- latest MAE: `{latest['mae_minutes']}` minutes\n"
        f"- latest p90 AE: `{latest['p90_absolute_error_minutes']}` minutes\n"
        f"- latest green incidents: `{latest['green_incidents']}`\n"
        f"- latest high-error incidents: `{latest['high_error_incidents']}`\n"
        f"- coverage: `{latest['coverage_status']}`\n"
        f"- research metric claim allowed: `{research_allowed}`\n"
        "- production accuracy claim allowed: `false`\n"
        "- production_send: `blocked`\n"
    )


def _render_peacon(latest: dict[str, Any] | None) -> str:
    incidents = int(latest["scorable_independent_incidents"]) if latest else 0
    status = str(latest["sample_size_status"]) if latest else "awaiting_first_scorable_incident"
    return (
        "# PEA-CON Prospective Evidence Trend\n\n"
        "ระบบสำหรับลูกค้าสื่อสารรายสำคัญใช้ทะเบียนผลประเมินแบบ append-only และนับตัวอย่างเป็นเหตุการณ์อิสระ "
        f"ปัจจุบันประเมินได้ {incidents} เหตุการณ์ จัดเป็น `{status}` จึงใช้ยืนยันการทำงานของสายข้อมูลเท่านั้น "
        "ยังไม่ใช้กล่าวอ้างความแม่นยำของโมเดล และ `production_send=blocked`\n"
    )


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None
