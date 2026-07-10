from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


MAPPING_VERSION = "alarm_mapping_v2"
CASE_COLUMNS = (
    "case_ref",
    "event_time",
    "classification",
    "evidence_basis",
    "use_for_training",
    "use_for_evaluation",
    "production_send",
)


def run_v2_lifecycle_audit(
    *,
    base_url: str,
    output_csv: str | Path,
    report_md: str | Path,
    summary_json: str | Path,
    peacon_md: str | Path,
    api_key: str | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    key = str(api_key or os.environ.get("AIS_INBOUND_API_KEY") or "").strip()
    if not key:
        raise ValueError("AIS_INBOUND_API_KEY is required")
    root = base_url.rstrip("/")
    metrics = _get_json(root + "/metrics", key)
    requests = _get_json(
        root + f"/api/v1/ais/outage-verifications?view=operator&limit={max(1, min(limit, 200))}",
        key,
    )
    intervals = _get_json(
        root + f"/api/v1/ais/truth-intervals?status=ALL&limit={max(1, min(limit, 200))}",
        key,
    )
    for label, payload in (("metrics", metrics), ("requests", requests), ("intervals", intervals)):
        if payload.get("production_send") != "blocked":
            raise ValueError(f"{label} production_send must remain blocked")
    return build_v2_lifecycle_audit(
        metrics,
        requests.get("items") or [],
        intervals.get("items") or [],
        output_csv=output_csv,
        report_md=report_md,
        summary_json=summary_json,
        peacon_md=peacon_md,
    )


def build_v2_lifecycle_audit(
    metrics: dict[str, Any],
    items: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
    *,
    output_csv: str | Path,
    report_md: str | Path,
    summary_json: str | Path,
    peacon_md: str | Path,
) -> dict[str, Any]:
    if metrics.get("production_send") != "blocked":
        raise ValueError("production_send must remain blocked")

    activation = _parse_time(metrics.get("v2_activation_first_seen_at"))
    v2_items = [item for item in items if item.get("semantic_mapping_version") == MAPPING_VERSION]
    v2_intervals = [row for row in intervals if row.get("semantic_mapping_version") == MAPPING_VERSION]
    event_counts: Counter[str] = Counter()
    by_meter: dict[str, list[tuple[datetime, str, str]]] = defaultdict(list)
    historical_outages: dict[str, list[datetime]] = defaultdict(list)

    for item in items:
        truth = item.get("truth_observation") or {}
        event_type = str(truth.get("event_type") or "UNKNOWN").strip().upper()
        event_time = _parse_time(item.get("detected_at") or item.get("received_at"))
        meter_hash = str((item.get("meter") or {}).get("hash") or "").strip()
        mapping = str(item.get("semantic_mapping_version") or "legacy").strip()
        if event_time is None or not meter_hash:
            continue
        if mapping == MAPPING_VERSION:
            event_counts[event_type] += 1
            validation = str(truth.get("validation_status") or "").strip()
            by_meter[meter_hash].append((event_time, event_type, validation))
        elif event_type == "OUTAGE" and (activation is None or event_time < activation):
            historical_outages[meter_hash].append(event_time)

    for row in intervals:
        mapping = str(row.get("semantic_mapping_version") or "legacy").strip()
        meter_hash = str((row.get("meter") or {}).get("hash") or "").strip()
        outage_time = _parse_time(row.get("outage_at"))
        if mapping != MAPPING_VERSION and meter_hash and outage_time is not None:
            historical_outages[meter_hash].append(outage_time)

    clean_intervals = []
    invalid_closed_intervals = []
    for row in v2_intervals:
        duration = _float_or_none(row.get("duration_minutes"))
        is_clean = (
            row.get("pair_status") == "CLOSED"
            and row.get("bridge_status") == "METER_STATE_MODEL_READY"
            and duration is not None
            and 5 < duration <= 1440
            and _parse_time(row.get("restore_at")) is not None
        )
        if is_clean:
            clean_intervals.append(row)
        elif row.get("pair_status") == "CLOSED":
            invalid_closed_intervals.append(row)

    cases = []
    classification_counts: Counter[str] = Counter()
    for item in v2_items:
        truth = item.get("truth_observation") or {}
        if str(truth.get("validation_status") or "") != "REVIEW_NO_OPEN_INTERVAL":
            continue
        event_time = _parse_time(item.get("detected_at") or item.get("received_at"))
        meter_hash = str((item.get("meter") or {}).get("hash") or "").strip()
        request_ref = str(item.get("request_ref") or "").strip()
        classification, basis = _classify_no_open_restore(
            event_time=event_time,
            meter_hash=meter_hash,
            current_events=by_meter.get(meter_hash, []),
            historical_outages=historical_outages.get(meter_hash, []),
            activation=activation,
        )
        classification_counts[classification] += 1
        cases.append(
            {
                "case_ref": _case_ref(request_ref, meter_hash, event_time),
                "event_time": event_time.isoformat().replace("+00:00", "Z") if event_time else "",
                "classification": classification,
                "evidence_basis": basis,
                "use_for_training": "FALSE",
                "use_for_evaluation": "FALSE",
                "production_send": "blocked",
            }
        )

    bounded_evidence_missing = classification_counts["bounded_window_evidence_missing"]
    sequence_conflicts = classification_counts["v2_sequence_conflict"]
    no_open_count = len(cases)
    restore_count = int(metrics.get("v2_restore_events") or event_counts["RESTORE"])
    no_open_ratio = no_open_count / restore_count if restore_count else 0.0
    lifecycle_review_count = bounded_evidence_missing + sequence_conflicts
    lifecycle_review_ratio = lifecycle_review_count / restore_count if restore_count else 0.0
    if invalid_closed_intervals:
        gate_status = "closed_pair_integrity_blocked"
    elif lifecycle_review_count:
        gate_status = "bounded_lifecycle_evidence_review_required"
    elif no_open_count:
        gate_status = "activation_backlog_or_duplicate_restore_observed"
    elif len(clean_intervals) < 30:
        gate_status = "prospective_capture_accumulating"
    else:
        gate_status = "incident_grouping_ready"

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CASE_COLUMNS)
        writer.writeheader()
        writer.writerows(cases)

    summary = {
        "gate_status": gate_status,
        "semantic_mapping_version": MAPPING_VERSION,
        "activation_first_seen_at": metrics.get("v2_activation_first_seen_at") or "",
        "operator_window_rows": len(items),
        "v2_operator_rows": len(v2_items),
        "v2_outage_events": int(metrics.get("v2_outage_events") or event_counts["OUTAGE"]),
        "v2_restore_events": restore_count,
        "v2_open_intervals": int(metrics.get("v2_open_intervals") or 0),
        "v2_model_ready_rows": int(metrics.get("v2_model_ready_rows") or 0),
        "clean_intervals_in_window": len(clean_intervals),
        "invalid_closed_intervals_in_window": len(invalid_closed_intervals),
        "restore_without_open": no_open_count,
        "restore_without_open_ratio": round(no_open_ratio, 4),
        "restore_without_open_explained_context": no_open_count - lifecycle_review_count,
        "restore_without_open_requires_review": lifecycle_review_count,
        "lifecycle_review_ratio": round(lifecycle_review_ratio, 4),
        "classification_counts": dict(sorted(classification_counts.items())),
        "minimum_independent_incidents": 30,
        "training_allowed": False,
        "evaluation_allowed": False,
        "production_send": "blocked",
        "output_csv": str(output),
        "report_md": str(report_md),
        "peacon_md": str(peacon_md),
    }
    summary_path = Path(summary_json)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = Path(report_md)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "# Prospective AIS v2 Lifecycle Quality Gate\n\n"
        "- วิธีตรวจ: authenticated GET แบบ one-shot เท่านั้น\n"
        f"- สถานะ: `{gate_status}`\n"
        f"- v2 OUTAGE: `{summary['v2_outage_events']}`\n"
        f"- v2 RESTORE: `{summary['v2_restore_events']}`\n"
        f"- v2 open intervals: `{summary['v2_open_intervals']}`\n"
        f"- v2 model-ready rows: `{summary['v2_model_ready_rows']}`\n"
        f"- RESTORE without open: `{no_open_count}` ({no_open_ratio:.1%})\n"
        f"- อธิบายได้จาก preactivation/duplicate context: `{no_open_count - lifecycle_review_count}`\n"
        f"- หลักฐานใน bounded window ยังไม่พอหรือ sequence ขัดแย้ง: `{lifecycle_review_count}` ({lifecycle_review_ratio:.1%})\n"
        f"- การจำแนก: `{json.dumps(summary['classification_counts'], ensure_ascii=False, sort_keys=True)}`\n"
        f"- closed pair ที่ integrity ไม่ผ่าน: `{len(invalid_closed_intervals)}`\n"
        "- ใช้ train/evaluation: `FALSE` จนกว่าจะผ่าน incident grouping และมีอย่างน้อย 30 เหตุการณ์อิสระ\n"
        "- production_send: `blocked`\n\n"
        "RESTORE ที่ไม่มี open interval ถูกเก็บเป็น audit/review เท่านั้น ไม่ถูกนำไปสร้าง target หรือทำให้จำนวน clean truth สูงขึ้น\n",
        encoding="utf-8",
    )

    peacon = Path(peacon_md)
    peacon.parent.mkdir(parents=True, exist_ok=True)
    peacon.write_text(
        "# PEA-CON Prospective Lifecycle Governance Update\n\n"
        "ระบบสำหรับลูกค้าสื่อสารรายสำคัญแยกเหตุการณ์ที่จับคู่ OUTAGE/RESTORE ได้ตาม prospective meter-state lifecycle "
        "ออกจาก RESTORE ที่ไม่พบ open interval อย่างชัดเจน รายการที่จับคู่ไม่ได้ถูกเก็บเป็น audit/review และไม่ใช้ train, "
        "คำนวณความแม่นยำ หรือเพิ่มจำนวนหลักฐานผ่านเกณฑ์ แนวทางนี้รักษา provenance และป้องกันการทำให้ผลโมเดลดูดีจากข้อมูลที่ยังอธิบายไม่ได้ "
        "โดยระบบยังอยู่ใน shadow mode และ `production_send=blocked`\n",
        encoding="utf-8",
    )
    return summary


def _classify_no_open_restore(
    *,
    event_time: datetime | None,
    meter_hash: str,
    current_events: list[tuple[datetime, str, str]],
    historical_outages: list[datetime],
    activation: datetime | None,
) -> tuple[str, str]:
    if event_time is None or not meter_hash:
        return "missing_redacted_identity_or_time", "operator row lacks a usable redacted meter hash or event time"
    prior = sorted(event for event in current_events if event[0] < event_time)
    if any(event_type == "RESTORE" for _, event_type, _ in prior):
        return "duplicate_restore_after_v2_restore", "same meter has an earlier prospective RESTORE in the operator window"
    if any(event_type == "OUTAGE" for _, event_type, _ in prior):
        return "v2_sequence_conflict", "same meter has an earlier v2 OUTAGE but ledger reports no open interval"
    if historical_outages and (activation is None or event_time >= activation):
        return "preactivation_backlog_restore", "same meter has a preactivation OUTAGE or interval in the bounded evidence window"
    return "bounded_window_evidence_missing", "no preceding outage or restore evidence is visible in the bounded GET-only evidence window"


def _case_ref(request_ref: str, meter_hash: str, event_time: datetime | None) -> str:
    seed = "|".join((request_ref, meter_hash, event_time.isoformat() if event_time else "missing"))
    return "v2case_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_json(url: str, api_key: str) -> dict[str, Any]:
    request = Request(
        url,
        method="GET",
        headers={"X-API-Key": api_key, "Accept": "application/json", "User-Agent": "pea-ais-v2-audit/1.0"},
    )
    with urlopen(request, timeout=60) as response:  # nosec B310 - caller supplies the configured API base URL
        return json.loads(response.read().decode("utf-8"))
