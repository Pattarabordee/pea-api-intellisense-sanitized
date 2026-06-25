from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sqlite3
from statistics import mean
from typing import Any


TRIAGE_COLUMNS = (
    "event_id",
    "webex_message_ref",
    "event_time",
    "district",
    "device_type",
    "device_id",
    "feeder",
    "match_level",
    "match_confidence",
    "affected_count",
    "webex_device_interruption_class",
    "event_age_band",
    "ais_remaining_minutes",
    "ais_elapsed_since_start_minutes",
    "current_p50",
    "current_q10",
    "current_q90",
    "current_absolute_error",
    "current_covered_q10_q90",
    "ais_remaining_match_status",
    "ais_remaining_match_level",
    "ais_truth_match_status",
    "ais_truth_match_level",
    "ais_matched_site_count",
    "ais_matched_rows",
    "truth_quality",
    "primary_root_cause",
    "root_cause_flags",
    "recommended_action",
    "reportpo_bridge_policy",
)

SEGMENT_COLUMNS = (
    "dimension",
    "segment",
    "candidate_rows",
    "high_error_rows",
    "mean_absolute_error_minutes",
    "mean_remaining_minutes",
    "q10_q90_coverage",
)

HIGH_ERROR_MINUTES = 60.0
LATE_WEBEX_MINUTES = 30.0
SHORT_PREDICTION_RATIO = 0.5


def build_ais_first_error_triage(
    db_path: str | Path,
    readiness_csv: str | Path,
    remaining_audit_csv: str | Path,
    ais_truth_audit_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    segments_output: str | Path | None = None,
    *,
    high_error_minutes: float = HIGH_ERROR_MINUTES,
    late_webex_minutes: float = LATE_WEBEX_MINUTES,
) -> dict[str, Any]:
    event_to_message = _load_event_message_map(db_path)
    remaining_by_message = _read_by_key(remaining_audit_csv, "webex_message_id")
    ais_truth_by_message = _read_by_key(ais_truth_audit_csv, "webex_message_id")
    readiness_rows = _read_csv(readiness_csv)
    candidate_rows = [
        row
        for row in readiness_rows
        if row.get("notification_time_gate") == "shadow_etr_candidate"
        and row.get("evaluation_policy") == "sustained_outage_eligible"
    ]
    feeder_high_counts = _high_error_counts(candidate_rows, "feeder", high_error_minutes)
    device_high_counts = _high_error_counts(candidate_rows, "device_id", high_error_minutes)
    triage_rows = [
        _triage_row(
            row,
            event_to_message.get(row.get("event_id") or "", ""),
            remaining_by_message,
            ais_truth_by_message,
            feeder_high_counts,
            device_high_counts,
            high_error_minutes=high_error_minutes,
            late_webex_minutes=late_webex_minutes,
        )
        for row in candidate_rows
    ]
    _write_csv(output_csv, TRIAGE_COLUMNS, triage_rows)
    segment_rows = _build_segments(triage_rows, high_error_minutes)
    if segments_output:
        _write_csv(segments_output, SEGMENT_COLUMNS, segment_rows)
    summary = _summarize(readiness_rows, triage_rows, segment_rows, high_error_minutes, late_webex_minutes)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, triage_rows, segment_rows), encoding="utf-8-sig")
    return {
        **summary,
        "db_path": str(db_path),
        "readiness_csv": str(readiness_csv),
        "remaining_audit_csv": str(remaining_audit_csv),
        "ais_truth_audit_csv": str(ais_truth_audit_csv),
        "output_csv": str(output_csv),
        "segments_output": str(segments_output) if segments_output else None,
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def _triage_row(
    readiness: dict[str, str],
    message_id: str,
    remaining_by_message: dict[str, dict[str, str]],
    ais_truth_by_message: dict[str, dict[str, str]],
    feeder_high_counts: dict[str, int],
    device_high_counts: dict[str, int],
    *,
    high_error_minutes: float,
    late_webex_minutes: float,
) -> dict[str, str]:
    remaining = remaining_by_message.get(message_id, {})
    ais_truth = ais_truth_by_message.get(message_id, {})
    flags = _root_cause_flags(
        readiness,
        remaining,
        ais_truth,
        feeder_high_counts,
        device_high_counts,
        high_error_minutes=high_error_minutes,
        late_webex_minutes=late_webex_minutes,
    )
    primary = _primary_root_cause(flags, readiness, high_error_minutes)
    return {
        "event_id": readiness.get("event_id", ""),
        "webex_message_ref": readiness.get("webex_message_ref", ""),
        "event_time": readiness.get("event_time", ""),
        "district": readiness.get("district", ""),
        "device_type": readiness.get("device_type", ""),
        "device_id": readiness.get("device_id", ""),
        "feeder": readiness.get("feeder", ""),
        "match_level": readiness.get("match_level", ""),
        "match_confidence": readiness.get("match_confidence", ""),
        "affected_count": readiness.get("affected_count", ""),
        "webex_device_interruption_class": readiness.get("webex_device_interruption_class", ""),
        "event_age_band": readiness.get("event_age_band", ""),
        "ais_remaining_minutes": readiness.get("remaining_actual_minutes", ""),
        "ais_elapsed_since_start_minutes": readiness.get("max_elapsed_since_ais_start_minutes", ""),
        "current_p50": readiness.get("current_p50", ""),
        "current_q10": readiness.get("current_q10", ""),
        "current_q90": readiness.get("current_q90", ""),
        "current_absolute_error": readiness.get("current_absolute_error", ""),
        "current_covered_q10_q90": readiness.get("current_covered_q10_q90", ""),
        "ais_remaining_match_status": remaining.get("match_status", ""),
        "ais_remaining_match_level": _safe_label(remaining.get("match_level", "")),
        "ais_truth_match_status": ais_truth.get("match_status", ""),
        "ais_truth_match_level": _safe_label(ais_truth.get("match_level", "")),
        "ais_matched_site_count": remaining.get("matched_site_count") or ais_truth.get("matched_site_count", ""),
        "ais_matched_rows": remaining.get("matched_ais_rows") or ais_truth.get("matched_ais_rows", ""),
        "truth_quality": remaining.get("truth_quality") or ais_truth.get("truth_quality", ""),
        "primary_root_cause": primary,
        "root_cause_flags": ";".join(flags),
        "recommended_action": _recommended_action(primary),
        "reportpo_bridge_policy": "blocked_no_shared_key_do_not_use_cl_datetime",
    }


def _root_cause_flags(
    readiness: dict[str, str],
    remaining: dict[str, str],
    ais_truth: dict[str, str],
    feeder_high_counts: dict[str, int],
    device_high_counts: dict[str, int],
    *,
    high_error_minutes: float,
    late_webex_minutes: float,
) -> list[str]:
    flags: list[str] = []
    remaining_minutes = _to_float(readiness.get("remaining_actual_minutes"))
    elapsed = _to_float(readiness.get("max_elapsed_since_ais_start_minutes"))
    p50 = _to_float(readiness.get("current_p50"))
    error = _to_float(readiness.get("current_absolute_error")) or 0.0
    confidence = _to_float(readiness.get("match_confidence")) or 0.0
    affected_count = _to_float(readiness.get("affected_count")) or 0.0
    state = str(readiness.get("webex_device_interruption_class") or "")
    match_level = str(readiness.get("match_level") or "")
    truth_quality = str(remaining.get("truth_quality") or ais_truth.get("truth_quality") or "").strip().upper()
    truth_notes = f"{remaining.get('truth_notes', '')};{ais_truth.get('truth_notes', '')}".lower()

    if truth_quality and truth_quality != "OK":
        flags.append("truth_quality_review")
    if remaining_minutes is not None and remaining_minutes > 1440:
        flags.append("truth_duration_gt_24h_review")
    if any(token in truth_notes for token in ("duplicate", "flapping", "invalid", "review")):
        flags.append("truth_interval_review")
    if match_level in {"", "feeder"} or confidence < 0.8 or affected_count <= 0:
        flags.append("topology_or_matching_review")
    if state == "momentary_le_1m" and remaining_minutes is not None and remaining_minutes > 5:
        flags.append("webex_momentary_but_ais_sustained")
    if elapsed is not None and elapsed >= late_webex_minutes:
        flags.append("webex_late_after_ais_start")
    if remaining_minutes is not None and p50 is not None and error >= high_error_minutes and p50 < remaining_minutes:
        flags.append("model_underestimated_remaining")
    if (
        remaining_minutes is not None
        and p50 is not None
        and remaining_minutes > 0
        and p50 <= remaining_minutes * SHORT_PREDICTION_RATIO
        and error >= high_error_minutes
    ):
        flags.append("model_prediction_less_than_half_remaining")
    if _bool_false(readiness.get("current_covered_q10_q90")):
        flags.append("prediction_interval_miss")
    feeder = readiness.get("feeder") or ""
    device = readiness.get("device_id") or ""
    if feeder and feeder_high_counts.get(feeder, 0) >= 3:
        flags.append("repeated_high_error_feeder")
    if device and device_high_counts.get(device, 0) >= 3:
        flags.append("repeated_high_error_device")
    if not flags:
        flags.append("no_major_error_signal")
    return _dedupe(flags)


def _primary_root_cause(flags: list[str], readiness: dict[str, str], high_error_minutes: float) -> str:
    error = _to_float(readiness.get("current_absolute_error")) or 0.0
    if "truth_quality_review" in flags or "truth_duration_gt_24h_review" in flags or "truth_interval_review" in flags:
        return "truth_quality_review"
    if "topology_or_matching_review" in flags:
        return "topology_or_matching_review"
    if "webex_momentary_but_ais_sustained" in flags:
        return "webex_momentary_long_ais_interval"
    if "webex_late_after_ais_start" in flags:
        return "webex_late_after_ais_start"
    if "model_underestimated_remaining" in flags:
        return "model_underestimation"
    if "prediction_interval_miss" in flags:
        return "prediction_interval_calibration"
    if error < high_error_minutes:
        return "lower_error_shadow_candidate"
    return "general_model_error_review"


def _recommended_action(root_cause: str) -> str:
    return {
        "truth_quality_review": "Validate AIS outage/restore interval quality before tuning.",
        "topology_or_matching_review": "Repair protection/topology mapping before model changes.",
        "webex_momentary_long_ais_interval": "Compare Webex operation state with AIS active alarm state; add live AIS state features.",
        "webex_late_after_ais_start": "Model remaining restoration time from notification time; add elapsed-since-outage features.",
        "model_underestimation": "Build an AIS-history challenger by feeder/device after topology and truth checks.",
        "prediction_interval_calibration": "Recalibrate q10-q90 bands after root-cause cleanup.",
        "lower_error_shadow_candidate": "Keep in shadow monitoring; no immediate repair priority.",
        "general_model_error_review": "Inspect event details before deciding model or data repair.",
    }.get(root_cause, "Review manually before using for model decisions.")


def _build_segments(rows: list[dict[str, str]], high_error_minutes: float) -> list[dict[str, str]]:
    dimensions = ("primary_root_cause", "feeder", "device_type", "webex_device_interruption_class", "event_age_band")
    output = []
    for dimension in dimensions:
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            grouped[row.get(dimension) or "<blank>"].append(row)
        for segment, values in grouped.items():
            output.append(_segment_row(dimension, segment, values, high_error_minutes))
    return sorted(
        output,
        key=lambda row: (
            0 if row["dimension"] == "primary_root_cause" else 1,
            -_to_int(row["high_error_rows"]),
            -_to_int(row["candidate_rows"]),
            row["dimension"],
            row["segment"],
        ),
    )


def _segment_row(dimension: str, segment: str, rows: list[dict[str, str]], high_error_minutes: float) -> dict[str, str]:
    return {
        "dimension": dimension,
        "segment": segment,
        "candidate_rows": str(len(rows)),
        "high_error_rows": str(sum(1 for row in rows if (_to_float(row.get("current_absolute_error")) or 0) >= high_error_minutes)),
        "mean_absolute_error_minutes": _fmt(_mean(_numbers(rows, "current_absolute_error"))),
        "mean_remaining_minutes": _fmt(_mean(_numbers(rows, "ais_remaining_minutes"))),
        "q10_q90_coverage": _fmt(_coverage(rows, "current_covered_q10_q90"), digits=3),
    }


def _summarize(
    readiness_rows: list[dict[str, str]],
    triage_rows: list[dict[str, str]],
    segment_rows: list[dict[str, str]],
    high_error_minutes: float,
    late_webex_minutes: float,
) -> dict[str, Any]:
    root_counts = Counter(row["primary_root_cause"] for row in triage_rows)
    flag_counts = Counter(flag for row in triage_rows for flag in row.get("root_cause_flags", "").split(";") if flag)
    high_error_rows = [row for row in triage_rows if (_to_float(row.get("current_absolute_error")) or 0) >= high_error_minutes]
    metrics = {
        "rows": len(triage_rows),
        "mae": _fmt(_mean(_numbers(triage_rows, "current_absolute_error"))),
        "coverage": _fmt(_coverage(triage_rows, "current_covered_q10_q90"), digits=3),
    }
    return {
        "readiness_rows": len(readiness_rows),
        "customer_facing_candidate_rows": len(triage_rows),
        "review_only_rows": len(readiness_rows) - len(triage_rows),
        "high_error_rows": len(high_error_rows),
        "high_error_minutes": high_error_minutes,
        "late_webex_minutes": late_webex_minutes,
        "candidate_metrics": metrics,
        "primary_root_cause_counts": dict(root_counts.most_common()),
        "root_cause_flag_counts": dict(flag_counts.most_common(12)),
        "top_primary_root_cause": root_counts.most_common(1)[0][0] if root_counts else "",
        "recommendation": _summary_recommendation(root_counts),
    }


def _summary_recommendation(root_counts: Counter[str]) -> str:
    if not root_counts:
        return "No customer-facing AIS truth candidates were available. Continue shadow capture."
    top = root_counts.most_common(1)[0][0]
    if top == "model_underestimation":
        return "Prioritize an AIS-history challenger after preserving current shadow-only gates."
    if top == "topology_or_matching_review":
        return "Prioritize protection/topology repair before any model tuning."
    if top in {"webex_late_after_ais_start", "webex_momentary_long_ais_interval"}:
        return "Prioritize live AIS alarm timing and notification-time features before model tuning."
    if top == "truth_quality_review":
        return "Prioritize AIS truth interval quality checks before model tuning."
    return "Keep production blocked; use this triage to choose the next data repair or challenger model."


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]], segments: list[dict[str, str]]) -> str:
    root_segments = [row for row in segments if row.get("dimension") == "primary_root_cause"]
    top_errors = sorted(rows, key=lambda row: -(_to_float(row.get("current_absolute_error")) or 0))[:15]
    lines = [
        "# AIS-First Shadow Error Triage",
        "",
        "This report uses AIS outage/restore truth as the primary customer-facing evidence. ReportPO/eRespond bridge evidence remains blocked unless a shared key or reviewed owner evidence is available.",
        "",
        "## Summary",
        "",
        f"- Readiness rows: {summary['readiness_rows']}",
        f"- Customer-facing candidates: {summary['customer_facing_candidate_rows']}",
        f"- Review-only rows excluded from primary triage: {summary['review_only_rows']}",
        f"- High-error candidates: {summary['high_error_rows']}",
        f"- Mean absolute error: {summary['candidate_metrics']['mae']}",
        f"- q10-q90 coverage: {summary['candidate_metrics']['coverage']}",
        f"- Top root cause: `{summary['top_primary_root_cause']}`",
        "",
        "## Primary Root Cause",
        "",
        "| Root cause | Candidates | High-error | MAE | Coverage |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in root_segments:
        lines.append(
            "| {segment} | {candidates} | {high} | {mae} | {coverage} |".format(
                segment=row["segment"],
                candidates=row["candidate_rows"],
                high=row["high_error_rows"],
                mae=row["mean_absolute_error_minutes"],
                coverage=row["q10_q90_coverage"],
            )
        )
    lines.extend(["", "## Frequent Flags", "", "| Flag | Rows |", "| --- | ---: |"])
    for flag, count in summary["root_cause_flag_counts"].items():
        lines.append(f"| {flag} | {count} |")
    lines.extend(
        [
            "",
            "## Top Error Rows",
            "",
            "| Event ref | Time | Device | Feeder | State | Remaining | p50 | Error | Root cause |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in top_errors:
        lines.append(
            "| {ref} | {time} | {device} | {feeder} | {state} | {remaining} | {p50} | {error} | {root} |".format(
                ref=row.get("webex_message_ref", ""),
                time=row.get("event_time", ""),
                device=row.get("device_id", ""),
                feeder=row.get("feeder", ""),
                state=row.get("webex_device_interruption_class", ""),
                remaining=row.get("ais_remaining_minutes", ""),
                p50=row.get("current_p50", ""),
                error=row.get("current_absolute_error", ""),
                root=row.get("primary_root_cause", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            str(summary["recommendation"]),
            "",
            "ReportPO/eRespond manual bridge candidates based on `cl_datetime` must not be approved as restoration truth.",
            "Do not tune or promote the model until the dominant root cause group is repaired or intentionally accepted.",
            "",
            "## Safety Notes",
            "",
            "- This is a shadow-only analysis and does not change customer notification behavior.",
            "- Outputs use redacted event references and operational context only.",
            "- Outputs omit source chat bodies, space identifiers, credential values, meter-id lists, and unnecessary customer identity fields.",
        ]
    )
    return "\n".join(lines) + "\n"


def _load_event_message_map(db_path: str | Path) -> dict[str, str]:
    path = Path(db_path)
    if not path.exists():
        return {}
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        return {
            str(event_id): str(message_id or "")
            for event_id, message_id in conn.execute(
                "SELECT event_id, webex_message_id FROM outage_events WHERE event_id IS NOT NULL"
            ).fetchall()
        }
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def _high_error_counts(rows: list[dict[str, str]], column: str, high_error_minutes: float) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        if (_to_float(row.get("current_absolute_error")) or 0.0) >= high_error_minutes:
            value = row.get(column) or ""
            if value:
                counter[value] += 1
    return dict(counter)


def _read_by_key(path: str | Path, key: str) -> dict[str, dict[str, str]]:
    output = {}
    for row in _read_csv(path):
        value = str(row.get(key) or "").strip()
        if value and value not in output:
            output[value] = row
    return output


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    if not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: str | Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _numbers(rows: list[dict[str, str]], column: str) -> list[float]:
    return [value for row in rows if (value := _to_float(row.get(column))) is not None]


def _mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _coverage(rows: list[dict[str, str]], column: str) -> float | None:
    values = [row.get(column) for row in rows if str(row.get(column) or "").strip()]
    if not values:
        return None
    return sum(1 for value in values if _bool_true(value)) / len(values)


def _fmt(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").strip()))
    except ValueError:
        return 0


def _bool_true(value: Any) -> bool:
    return str(value or "").strip().upper() in {"TRUE", "1", "YES", "Y"}


def _bool_false(value: Any) -> bool:
    return str(value or "").strip().upper() in {"FALSE", "0", "NO", "N"}


def _dedupe(values: list[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output


def _safe_label(value: Any) -> str:
    return str(value or "").replace("peano", "meter").replace("PEANO", "meter")
