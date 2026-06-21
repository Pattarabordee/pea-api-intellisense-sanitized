from __future__ import annotations

from collections import Counter
import csv
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN, GATE_Q50_MAE_MAX, MIN_SUSTAINED_ROWS_FOR_TUNING


SEGMENT_COLUMNS = (
    "dimension",
    "segment",
    "rows",
    "high_error_rows",
    "high_error_share",
    "underprediction_rows",
    "overprediction_rows",
    "mean_actual_minutes",
    "mean_p50_minutes",
    "q50_mae_minutes",
    "q10_q90_coverage",
    "recommended_challenger_lane",
)

QUEUE_COLUMNS = (
    "event_ref",
    "event_time",
    "district",
    "feeder",
    "device_id",
    "device_type",
    "match_level",
    "affected_count",
    "actual_restoration_minutes",
    "current_p50",
    "current_q10",
    "current_q90",
    "current_absolute_error",
    "current_covered_q10_q90",
    "duration_band",
    "error_direction",
    "event_age_band",
    "webex_device_interruption_class",
    "recommended_challenger_lane",
)


def build_ais_only_error_segmentation(
    ais_only_readiness_csv: str | Path,
    output_segments_csv: str | Path,
    output_queue_csv: str | Path,
    markdown_output: str | Path,
    *,
    notification_time_csv: str | Path | None = "runtime/notification_time_readiness.csv",
    high_error_minutes: float = 60.0,
) -> dict[str, Any]:
    notification_by_ref = _read_by_key(notification_time_csv, "webex_message_ref") if notification_time_csv else {}
    rows = [
        _metric_row(row, notification_by_ref.get(row.get("event_ref") or "", {}), high_error_minutes)
        for row in _read_csv(ais_only_readiness_csv)
        if row.get("source_lane") == "ais_truth_matched" and row.get("model_metric_included") == "true"
    ]
    high_error_rows = sorted(
        [row for row in rows if (_to_float(row.get("current_absolute_error")) or 0) >= high_error_minutes],
        key=lambda row: _to_float(row.get("current_absolute_error")) or -1,
        reverse=True,
    )
    segment_rows = _build_segments(rows, high_error_minutes)
    _write_csv(output_segments_csv, SEGMENT_COLUMNS, segment_rows)
    _write_csv(output_queue_csv, QUEUE_COLUMNS, high_error_rows)

    summary = _summary(rows, high_error_rows, segment_rows, high_error_minutes)
    output = Path(markdown_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_markdown(summary, high_error_rows, segment_rows), encoding="utf-8-sig")
    return {
        **summary,
        "ais_only_readiness_csv": str(ais_only_readiness_csv),
        "notification_time_csv": str(notification_time_csv) if notification_time_csv else None,
        "output_segments_csv": str(output_segments_csv),
        "output_queue_csv": str(output_queue_csv),
        "markdown_output": str(markdown_output),
    }


def _metric_row(row: dict[str, str], notification: dict[str, str], high_error_minutes: float) -> dict[str, str]:
    actual = _to_float(row.get("actual_restoration_minutes"))
    p50 = _to_float(row.get("current_p50"))
    error = _to_float(row.get("current_absolute_error"))
    direction = _error_direction(actual, p50, error, high_error_minutes)
    duration = _duration_band(actual)
    device_class = notification.get("webex_device_interruption_class", "")
    age_band = notification.get("event_age_band", "")
    lane = _challenger_lane(actual, p50, error, direction, duration, device_class, age_band, high_error_minutes)
    return {
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "district": row.get("district", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "device_type": notification.get("device_type", ""),
        "match_level": row.get("match_level", ""),
        "affected_count": row.get("affected_count", ""),
        "actual_restoration_minutes": row.get("actual_restoration_minutes", ""),
        "current_p50": row.get("current_p50", ""),
        "current_q10": row.get("current_q10", ""),
        "current_q90": row.get("current_q90", ""),
        "current_absolute_error": row.get("current_absolute_error", ""),
        "current_covered_q10_q90": row.get("current_covered_q10_q90", ""),
        "duration_band": duration,
        "error_direction": direction,
        "event_age_band": age_band,
        "webex_device_interruption_class": device_class,
        "recommended_challenger_lane": lane,
    }


def _build_segments(rows: list[dict[str, str]], high_error_minutes: float) -> list[dict[str, str]]:
    segments: list[dict[str, str]] = []
    for dimension in (
        "all",
        "district",
        "feeder",
        "device_id",
        "device_type",
        "match_level",
        "duration_band",
        "error_direction",
        "event_age_band",
        "webex_device_interruption_class",
        "recommended_challenger_lane",
    ):
        grouped = _group_rows(rows, dimension)
        for segment, group_rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
            segments.append(_segment_row(dimension, segment, group_rows, high_error_minutes))
    return segments


def _segment_row(dimension: str, segment: str, rows: list[dict[str, str]], high_error_minutes: float) -> dict[str, str]:
    high = [row for row in rows if (_to_float(row.get("current_absolute_error")) or 0) >= high_error_minutes]
    under = [row for row in rows if row.get("error_direction") == "underprediction"]
    over = [row for row in rows if row.get("error_direction") == "overprediction"]
    return {
        "dimension": dimension,
        "segment": segment,
        "rows": str(len(rows)),
        "high_error_rows": str(len(high)),
        "high_error_share": _fmt(len(high) / len(rows) if rows else None),
        "underprediction_rows": str(len(under)),
        "overprediction_rows": str(len(over)),
        "mean_actual_minutes": _fmt(_mean_number(rows, "actual_restoration_minutes")),
        "mean_p50_minutes": _fmt(_mean_number(rows, "current_p50")),
        "q50_mae_minutes": _fmt(_mean_number(rows, "current_absolute_error")),
        "q10_q90_coverage": _fmt(_coverage(rows, "current_covered_q10_q90")),
        "recommended_challenger_lane": _dominant_challenger_lane(rows),
    }


def _summary(
    rows: list[dict[str, str]],
    high_error_rows: list[dict[str, str]],
    segment_rows: list[dict[str, str]],
    high_error_minutes: float,
) -> dict[str, Any]:
    mae = _mean_number(rows, "current_absolute_error")
    coverage = _coverage(rows, "current_covered_q10_q90")
    return {
        "ais_truth_matched_rows": len(rows),
        "high_error_threshold_minutes": high_error_minutes,
        "high_error_rows": len(high_error_rows),
        "high_error_share": len(high_error_rows) / len(rows) if rows else None,
        "current_q50_mae_minutes": mae,
        "current_q10_q90_coverage": coverage,
        "model_gate_status": _gate_status(len(rows), mae, coverage),
        "top_feeders": dict(_top_counts(rows, "feeder")),
        "top_devices": dict(_top_counts(rows, "device_id")),
        "top_duration_bands": dict(_top_counts(rows, "duration_band")),
        "top_challenger_lanes": dict(_top_counts(rows, "recommended_challenger_lane")),
        "segment_rows": len(segment_rows),
        "recommendation": _recommendation(rows, high_error_rows, mae, coverage),
    }


def _render_markdown(
    summary: dict[str, Any],
    high_error_rows: list[dict[str, str]],
    segment_rows: list[dict[str, str]],
) -> str:
    lines = [
        "# AIS-Only Error Segmentation",
        "",
        "This report uses only `ais_truth_matched` rows from AIS-only readiness. PEA quarantine rows are excluded from metrics.",
        "",
        "## Summary",
        "",
        f"- AIS truth matched rows: {summary['ais_truth_matched_rows']}",
        f"- High-error rows (>={summary['high_error_threshold_minutes']:g} min): {summary['high_error_rows']}",
        f"- High-error share: {_blank(summary['high_error_share'])}",
        f"- Current q50 MAE: {_blank(summary['current_q50_mae_minutes'])} min",
        f"- Current q10-q90 coverage: {_blank(summary['current_q10_q90_coverage'])}",
        f"- Model gate status: `{summary['model_gate_status']}`",
        "",
        "## Top Challenger Lanes",
        "",
        "| Lane | Rows |",
        "| --- | ---: |",
    ]
    for lane, count in summary["top_challenger_lanes"].items():
        lines.append(f"| `{lane}` | {count} |")
    lines.extend(
        [
            "",
            "## Top Error Segments",
            "",
            "| Dimension | Segment | Rows | High-error rows | MAE | Coverage | Lane |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in _top_segments(segment_rows):
        lines.append(
            f"| `{row.get('dimension', '')}` | {row.get('segment', '')} | {row.get('rows', '')} | "
            f"{row.get('high_error_rows', '')} | {row.get('q50_mae_minutes', '')} | "
            f"{row.get('q10_q90_coverage', '')} | `{row.get('recommended_challenger_lane', '')}` |"
        )
    lines.extend(
        [
            "",
            "## High-Error Queue",
            "",
            "| Event | Time | Feeder | Device | Actual | P50 | Error | Direction | Lane |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in high_error_rows[:20]:
        lines.append(
            f"| `{row.get('event_ref', '')}` | {row.get('event_time', '')} | {row.get('feeder', '')} | "
            f"{row.get('device_id', '')} | {row.get('actual_restoration_minutes', '')} | "
            f"{row.get('current_p50', '')} | {row.get('current_absolute_error', '')} | "
            f"{row.get('error_direction', '')} | `{row.get('recommended_challenger_lane', '')}` |"
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            str(summary["recommendation"]),
            "",
            "## Guardrails",
            "",
            "- PEA/SFSD/ReportPO quarantine rows are not used in MAE, coverage, or challenger selection.",
            "- WebEx remains trigger/device evidence; AIS outage/restore remains customer-facing truth.",
            "- This report excludes customer meter identifier lists, verbatim WebEx text, room IDs, tokens, secrets, and customer registration names.",
        ]
    )
    return "\n".join(lines) + "\n"


def _recommendation(
    rows: list[dict[str, str]],
    high_error_rows: list[dict[str, str]],
    mae: float | None,
    coverage: float | None,
) -> str:
    if len(rows) < MIN_SUSTAINED_ROWS_FOR_TUNING:
        return "Collect more AIS-matched sustained truth before model tuning."
    if mae is not None and mae <= GATE_Q50_MAE_MAX and coverage is not None and GATE_COVERAGE_MIN <= coverage <= GATE_COVERAGE_MAX:
        return "AIS-only metric gate passes; prepare a shadow challenger promotion review, not production send."
    lane_counts = Counter(row.get("recommended_challenger_lane", "") for row in high_error_rows)
    top_lane = lane_counts.most_common(1)[0][0] if lane_counts else "baseline_recalibration"
    if top_lane in {"long_outage_tail_challenger", "remaining_time_underprediction_challenger"}:
        return "Build an AIS-only remaining-time challenger focused on long-outage underprediction before using any PEA context."
    if top_lane == "interval_width_calibration":
        return "Tune q10-q90 interval width on AIS-only truth before changing feature sources."
    return "Start with AIS-only error calibration, then add owner-approved context only if residual long-outage misses remain."


def _challenger_lane(
    actual: float | None,
    p50: float | None,
    error: float | None,
    direction: str,
    duration_band: str,
    device_class: str,
    age_band: str,
    high_error_minutes: float,
) -> str:
    if error is None or error < high_error_minutes:
        return "baseline_monitor"
    if direction == "underprediction" and duration_band in {"over_360m", "181_360m"}:
        return "long_outage_tail_challenger"
    if direction == "underprediction":
        return "remaining_time_underprediction_challenger"
    if direction == "overprediction":
        return "short_restore_overprediction_challenger"
    return "interval_width_calibration"


def _error_direction(actual: float | None, p50: float | None, error: float | None, high_error_minutes: float) -> str:
    if actual is None or p50 is None or error is None:
        return "unknown"
    if error < high_error_minutes:
        return "within_threshold"
    if p50 < actual:
        return "underprediction"
    if p50 > actual:
        return "overprediction"
    return "exact"


def _duration_band(actual: float | None) -> str:
    if actual is None:
        return "missing"
    if actual <= 30:
        return "lte_30m"
    if actual <= 60:
        return "31_60m"
    if actual <= 180:
        return "61_180m"
    if actual <= 360:
        return "181_360m"
    return "over_360m"


def _group_rows(rows: list[dict[str, str]], dimension: str) -> dict[str, list[dict[str, str]]]:
    if dimension == "all":
        return {"all": rows}
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        key = row.get(dimension) or "<blank>"
        groups.setdefault(key, []).append(row)
    return groups


def _dominant_challenger_lane(rows: list[dict[str, str]]) -> str:
    counts = Counter(row.get("recommended_challenger_lane", "") for row in rows)
    return counts.most_common(1)[0][0] if counts else ""


def _top_segments(rows: list[dict[str, str]], limit: int = 15) -> list[dict[str, str]]:
    filtered = [
        row for row in rows
        if row.get("dimension") != "all" and (_to_float(row.get("high_error_rows")) or 0) > 0
    ]
    return sorted(
        filtered,
        key=lambda row: (
            -(_to_float(row.get("high_error_rows")) or 0),
            -(_to_float(row.get("q50_mae_minutes")) or 0),
            row.get("dimension", ""),
            row.get("segment", ""),
        ),
    )[:limit]


def _top_counts(rows: list[dict[str, str]], column: str, limit: int = 8) -> list[tuple[str, int]]:
    return Counter(row.get(column) or "<blank>" for row in rows).most_common(limit)


def _read_by_key(path: str | Path | None, key: str) -> dict[str, dict[str, str]]:
    if not path or not Path(path).exists():
        return {}
    output: dict[str, dict[str, str]] = {}
    for row in _read_csv(path):
        value = row.get(key) or ""
        if value and value not in output:
            output[value] = row
    return output


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    source = Path(path)
    if not source.exists():
        return []
    with source.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: str | Path, columns: Iterable[str], rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _mean_number(rows: list[dict[str, str]], column: str) -> float | None:
    values = [value for value in (_to_float(row.get(column)) for row in rows) if value is not None]
    return mean(values) if values else None


def _coverage(rows: list[dict[str, str]], column: str) -> float | None:
    values = [value for value in (_to_bool(row.get(column)) for row in rows) if value is not None]
    return sum(1 for value in values if value) / len(values) if values else None


def _gate_status(rows: int, mae: float | None, coverage: float | None) -> str:
    if rows < MIN_SUSTAINED_ROWS_FOR_TUNING:
        return "blocked_insufficient_ais_truth"
    if mae is None or coverage is None:
        return "blocked_missing_metrics"
    if mae <= GATE_Q50_MAE_MAX and GATE_COVERAGE_MIN <= coverage <= GATE_COVERAGE_MAX:
        return "shadow_gate_pass_candidate"
    return "blocked_metric_gate_failed"


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_bool(value: Any) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return ""
    rounded = round(value, digits)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded).rstrip("0").rstrip(".")


def _blank(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return _fmt(value)
    return str(value)
