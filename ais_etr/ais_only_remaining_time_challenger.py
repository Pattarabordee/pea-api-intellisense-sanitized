from __future__ import annotations

from collections import Counter
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sqlite3
from statistics import mean
from typing import Any, Iterable

from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN, GATE_Q50_MAE_MAX


CHALLENGER_COLUMNS = (
    "event_id",
    "event_ref",
    "event_time",
    "district",
    "feeder",
    "device_id",
    "match_level",
    "affected_count",
    "active_elapsed_minutes",
    "event_age_band",
    "webex_device_interruption_class",
    "actual_restoration_minutes",
    "current_p50",
    "current_q10",
    "current_q90",
    "current_absolute_error",
    "current_covered_q10_q90",
    "active_state_p50",
    "active_state_absolute_error",
    "active_state_covered_q10_q90",
    "challenger_source",
    "challenger_rows_used",
    "selected_q10",
    "selected_q50",
    "selected_q75",
    "selected_q90",
    "tail_uplift_applied",
    "challenger_p50",
    "challenger_q10",
    "challenger_q90",
    "challenger_absolute_error",
    "challenger_covered_q10_q90",
    "error_delta_challenger_minus_current",
    "challenger_notes",
)

SEGMENT_COLUMNS = (
    "dimension",
    "segment",
    "rows",
    "current_mae",
    "active_state_mae",
    "challenger_mae",
    "mae_delta_challenger_minus_current",
    "current_coverage",
    "active_state_coverage",
    "challenger_coverage",
    "current_high_error_rows",
    "challenger_high_error_rows",
)


@dataclass(frozen=True)
class TruthInterval:
    meter_id: str
    outage_start_time: datetime
    power_restore_time: datetime
    actual_restoration_minutes: float


def build_ais_only_remaining_time_challenger(
    db_path: str | Path,
    ais_only_readiness_csv: str | Path,
    notification_time_csv: str | Path,
    ais_truth_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    segments_output: str | Path | None = None,
    *,
    active_state_csv: str | Path | None = "runtime/shadow_active_state_remaining_challenger.csv",
    min_affected_history_rows: int = 3,
    min_segment_rows: int = 5,
    tail_uplift_threshold_minutes: float = 180.0,
    high_error_minutes: float = 60.0,
) -> dict[str, Any]:
    if min_affected_history_rows < 1:
        raise ValueError("min_affected_history_rows must be at least 1")
    if min_segment_rows < 1:
        raise ValueError("min_segment_rows must be at least 1")

    notification_by_ref = _read_by_key(notification_time_csv, "webex_message_ref")
    active_by_ref = _read_by_key(active_state_csv, "webex_message_ref") if active_state_csv else {}
    affected_by_event = _load_affected_meters_by_event(db_path)
    intervals = _load_truth_intervals(ais_truth_csv)
    intervals_by_meter: dict[str, list[TruthInterval]] = {}
    for interval in intervals:
        intervals_by_meter.setdefault(interval.meter_id, []).append(interval)
    for values in intervals_by_meter.values():
        values.sort(key=lambda item: item.power_restore_time)

    candidate_rows = [
        row
        for row in _read_csv(ais_only_readiness_csv)
        if row.get("source_lane") == "ais_truth_matched"
        and row.get("model_metric_included") == "true"
        and (_to_float(row.get("actual_restoration_minutes")) or 0) > 5
    ]
    candidate_rows.sort(key=lambda row: _parse_dt(row.get("event_time")) or datetime.max)

    output_rows: list[dict[str, str]] = []
    prior_shadow_rows: list[dict[str, str]] = []
    for row in candidate_rows:
        event_id = row.get("event_id") or ""
        enriched = _build_one_row(
            row,
            notification_by_ref.get(row.get("event_ref") or "", {}),
            active_by_ref.get(row.get("event_ref") or "", {}),
            affected_by_event.get(event_id, set()),
            intervals,
            intervals_by_meter,
            prior_shadow_rows,
            min_affected_history_rows=min_affected_history_rows,
            min_segment_rows=min_segment_rows,
            tail_uplift_threshold_minutes=tail_uplift_threshold_minutes,
        )
        output_rows.append(enriched)
        prior_shadow_rows.append(enriched)

    _write_csv(output_csv, CHALLENGER_COLUMNS, output_rows)
    segments = _build_segments(output_rows, high_error_minutes)
    if segments_output:
        _write_csv(segments_output, SEGMENT_COLUMNS, segments)
    summary = _summary(output_rows, segments, min_affected_history_rows, min_segment_rows, tail_uplift_threshold_minutes, high_error_minutes)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, output_rows, segments), encoding="utf-8-sig")
    return {
        **summary,
        "db_path": str(db_path),
        "ais_only_readiness_csv": str(ais_only_readiness_csv),
        "notification_time_csv": str(notification_time_csv),
        "ais_truth_csv": str(ais_truth_csv),
        "active_state_csv": str(active_state_csv) if active_state_csv else None,
        "output_csv": str(output_csv),
        "segments_output": str(segments_output) if segments_output else None,
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def _build_one_row(
    row: dict[str, str],
    notification: dict[str, str],
    active_state: dict[str, str],
    affected_meters: set[str],
    intervals: list[TruthInterval],
    intervals_by_meter: dict[str, list[TruthInterval]],
    prior_shadow_rows: list[dict[str, str]],
    *,
    min_affected_history_rows: int,
    min_segment_rows: int,
    tail_uplift_threshold_minutes: float,
) -> dict[str, str]:
    event_dt = _parse_dt(row.get("event_time"))
    elapsed = _first_float(
        notification.get("max_elapsed_since_ais_start_minutes"),
        active_state.get("active_elapsed_minutes"),
    )
    actual = _to_float(row.get("actual_restoration_minutes"))
    current_p50 = _to_float(row.get("current_p50"))
    current_q10 = _to_float(row.get("current_q10"))
    current_q90 = _to_float(row.get("current_q90"))
    active_p50 = _to_float(active_state.get("active_p50"))
    active_error = _to_float(active_state.get("active_absolute_error"))
    active_covered = active_state.get("active_covered_q10_q90", "")
    values, source, notes = _select_prior_values(
        row,
        event_dt,
        elapsed,
        affected_meters,
        intervals,
        intervals_by_meter,
        prior_shadow_rows,
        min_affected_history_rows=min_affected_history_rows,
        min_segment_rows=min_segment_rows,
    )

    selected_q10 = selected_q50 = selected_q75 = selected_q90 = None
    challenger_p50 = current_p50
    challenger_q10 = current_q10
    challenger_q90 = current_q90
    tail_uplift = False
    if values:
        selected_q10 = _quantile(values, 0.1)
        selected_q50 = _quantile(values, 0.5)
        selected_q75 = _quantile(values, 0.75)
        selected_q90 = _quantile(values, 0.9)
        challenger_p50 = max(_or_zero(current_p50), selected_q50)
        if selected_q90 >= tail_uplift_threshold_minutes and _or_zero(current_q90) < selected_q90:
            if selected_q75 > challenger_p50:
                challenger_p50 = selected_q75
            tail_uplift = True
        challenger_q10 = max(0.0, min(challenger_p50, _or_zero(selected_q10)))
        challenger_q90 = max(_or_zero(current_q90), challenger_p50, selected_q90)

    current_error = abs(current_p50 - actual) if current_p50 is not None and actual is not None else None
    challenger_error = abs(challenger_p50 - actual) if challenger_p50 is not None and actual is not None else None
    return {
        "event_id": row.get("event_id", ""),
        "event_ref": row.get("event_ref", ""),
        "event_time": row.get("event_time", ""),
        "district": row.get("district", ""),
        "feeder": row.get("feeder", ""),
        "device_id": row.get("device_id", ""),
        "match_level": row.get("match_level", ""),
        "affected_count": row.get("affected_count", ""),
        "active_elapsed_minutes": _fmt(elapsed),
        "event_age_band": notification.get("event_age_band", ""),
        "webex_device_interruption_class": notification.get("webex_device_interruption_class", ""),
        "actual_restoration_minutes": _fmt(actual),
        "current_p50": _fmt(current_p50),
        "current_q10": _fmt(current_q10),
        "current_q90": _fmt(current_q90),
        "current_absolute_error": _fmt(current_error),
        "current_covered_q10_q90": _bool_str(_covered(actual, current_q10, current_q90)),
        "active_state_p50": _fmt(active_p50),
        "active_state_absolute_error": _fmt(active_error),
        "active_state_covered_q10_q90": _normalize_bool_text(active_covered),
        "challenger_source": source,
        "challenger_rows_used": str(len(values)),
        "selected_q10": _fmt(selected_q10),
        "selected_q50": _fmt(selected_q50),
        "selected_q75": _fmt(selected_q75),
        "selected_q90": _fmt(selected_q90),
        "tail_uplift_applied": _bool_str(tail_uplift),
        "challenger_p50": _fmt(challenger_p50),
        "challenger_q10": _fmt(challenger_q10),
        "challenger_q90": _fmt(challenger_q90),
        "challenger_absolute_error": _fmt(challenger_error),
        "challenger_covered_q10_q90": _bool_str(_covered(actual, challenger_q10, challenger_q90)),
        "error_delta_challenger_minus_current": _fmt(_delta(challenger_error, current_error)),
        "challenger_notes": notes,
    }


def _select_prior_values(
    row: dict[str, str],
    event_dt: datetime | None,
    elapsed: float | None,
    affected_meters: set[str],
    intervals: list[TruthInterval],
    intervals_by_meter: dict[str, list[TruthInterval]],
    prior_shadow_rows: list[dict[str, str]],
    *,
    min_affected_history_rows: int,
    min_segment_rows: int,
) -> tuple[list[float], str, str]:
    if event_dt is not None and affected_meters:
        affected_values = [
            value
            for meter in affected_meters
            for interval in intervals_by_meter.get(meter, [])
            if interval.power_restore_time < event_dt
            if (value := _remaining_value(interval.actual_restoration_minutes, elapsed)) is not None
        ]
        if len(affected_values) >= min_affected_history_rows:
            return affected_values, "affected_meter_history", f"affected_meter_history_rows={len(affected_values)}"

    device = _normalize_key(row.get("device_id"))
    feeder = _normalize_key(row.get("feeder"))
    device_values = [
        value
        for prior in prior_shadow_rows
        if _normalize_key(prior.get("device_id")) == device
        if (value := _to_float(prior.get("actual_restoration_minutes"))) is not None
    ]
    if len(device_values) >= min_segment_rows:
        return device_values, "prior_same_device_remaining", f"device_prior_rows={len(device_values)}"

    feeder_values = [
        value
        for prior in prior_shadow_rows
        if _normalize_key(prior.get("feeder")) == feeder
        if (value := _to_float(prior.get("actual_restoration_minutes"))) is not None
    ]
    if len(feeder_values) >= min_segment_rows:
        return feeder_values, "prior_same_feeder_remaining", f"feeder_prior_rows={len(feeder_values)}"

    if event_dt is not None:
        global_values = [
            value
            for interval in intervals
            if interval.power_restore_time < event_dt
            if (value := _remaining_value(interval.actual_restoration_minutes, elapsed)) is not None
        ]
        if global_values:
            return global_values, "global_ais_prior", f"global_ais_prior_rows={len(global_values)}"

    return [], "current_model_only", "no_time_respecting_ais_only_prior_available"


def _remaining_value(actual_restoration_minutes: float, elapsed: float | None) -> float | None:
    if elapsed is None:
        return actual_restoration_minutes
    remaining = actual_restoration_minutes - elapsed
    return remaining if remaining >= 0 else None


def _build_segments(rows: list[dict[str, str]], high_error_minutes: float) -> list[dict[str, str]]:
    output = []
    for dimension in (
        "challenger_source",
        "feeder",
        "device_id",
        "event_age_band",
        "webex_device_interruption_class",
        "tail_uplift_applied",
    ):
        groups: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            groups.setdefault(row.get(dimension) or "<blank>", []).append(row)
        for segment, values in groups.items():
            output.append(_segment_row(dimension, segment, values, high_error_minutes))
    return sorted(output, key=lambda row: (row["dimension"], -_to_int(row["rows"]), row["segment"]))


def _segment_row(dimension: str, segment: str, rows: list[dict[str, str]], high_error_minutes: float) -> dict[str, str]:
    current_mae = _mean_or_none(_numbers(rows, "current_absolute_error"))
    active_mae = _mean_or_none(_numbers(rows, "active_state_absolute_error"))
    challenger_mae = _mean_or_none(_numbers(rows, "challenger_absolute_error"))
    return {
        "dimension": dimension,
        "segment": segment,
        "rows": str(len(rows)),
        "current_mae": _fmt(current_mae),
        "active_state_mae": _fmt(active_mae),
        "challenger_mae": _fmt(challenger_mae),
        "mae_delta_challenger_minus_current": _fmt(_delta(challenger_mae, current_mae)),
        "current_coverage": _fmt(_coverage(rows, "current_covered_q10_q90"), digits=3),
        "active_state_coverage": _fmt(_coverage(rows, "active_state_covered_q10_q90"), digits=3),
        "challenger_coverage": _fmt(_coverage(rows, "challenger_covered_q10_q90"), digits=3),
        "current_high_error_rows": str(sum(1 for value in _numbers(rows, "current_absolute_error") if value >= high_error_minutes)),
        "challenger_high_error_rows": str(sum(1 for value in _numbers(rows, "challenger_absolute_error") if value >= high_error_minutes)),
    }


def _summary(
    rows: list[dict[str, str]],
    segments: list[dict[str, str]],
    min_affected_history_rows: int,
    min_segment_rows: int,
    tail_uplift_threshold_minutes: float,
    high_error_minutes: float,
) -> dict[str, Any]:
    current_mae = _mean_or_none(_numbers(rows, "current_absolute_error"))
    active_mae = _mean_or_none(_numbers(rows, "active_state_absolute_error"))
    challenger_mae = _mean_or_none(_numbers(rows, "challenger_absolute_error"))
    current_coverage = _coverage(rows, "current_covered_q10_q90")
    active_coverage = _coverage(rows, "active_state_covered_q10_q90")
    challenger_coverage = _coverage(rows, "challenger_covered_q10_q90")
    source_counts = Counter(row.get("challenger_source") or "<blank>" for row in rows)
    return {
        "candidates": len(rows),
        "current_q50_mae_minutes": _round_or_none(current_mae),
        "active_state_q50_mae_minutes": _round_or_none(active_mae),
        "challenger_q50_mae_minutes": _round_or_none(challenger_mae),
        "challenger_minus_current_mae_minutes": _round_or_none(_delta(challenger_mae, current_mae)),
        "challenger_minus_active_state_mae_minutes": _round_or_none(_delta(challenger_mae, active_mae)),
        "current_q10_q90_coverage": _round_or_none(current_coverage, digits=3),
        "active_state_q10_q90_coverage": _round_or_none(active_coverage, digits=3),
        "challenger_q10_q90_coverage": _round_or_none(challenger_coverage, digits=3),
        "current_high_error_rows": sum(1 for value in _numbers(rows, "current_absolute_error") if value >= high_error_minutes),
        "challenger_high_error_rows": sum(1 for value in _numbers(rows, "challenger_absolute_error") if value >= high_error_minutes),
        "tail_uplift_rows": sum(1 for row in rows if row.get("tail_uplift_applied") == "TRUE"),
        "challenger_source_counts": dict(source_counts.most_common()),
        "min_affected_history_rows": min_affected_history_rows,
        "min_segment_rows": min_segment_rows,
        "tail_uplift_threshold_minutes": tail_uplift_threshold_minutes,
        "high_error_minutes": high_error_minutes,
        "challenger_gate_status": _gate_status(challenger_mae, challenger_coverage),
        "recommendation": _recommendation(current_mae, active_mae, challenger_mae, challenger_coverage),
        "segment_rows": len(segments),
    }


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]], segments: list[dict[str, str]]) -> str:
    source_segments = [row for row in segments if row.get("dimension") == "challenger_source"]
    improvements = sorted(
        [row for row in rows if _to_float(row.get("error_delta_challenger_minus_current")) is not None],
        key=lambda row: _to_float(row.get("error_delta_challenger_minus_current")) or 0,
    )[:10]
    residual = sorted(
        [row for row in rows if _to_float(row.get("challenger_absolute_error")) is not None],
        key=lambda row: _to_float(row.get("challenger_absolute_error")) or 0,
        reverse=True,
    )[:10]
    lines = [
        "# AIS-Only Remaining-Time Challenger v2",
        "",
        "This shadow diagnostic uses only AIS outage/restore truth plus WebEx trigger/device evidence. PEA/SFSD/ReportPO quarantine rows are excluded from metrics and fallback logic.",
        "",
        "## Summary",
        "",
        f"- Candidate rows: {summary['candidates']}",
        f"- Current q50 MAE: {_blank(summary['current_q50_mae_minutes'])} min",
        f"- Active-state q50 MAE: {_blank(summary['active_state_q50_mae_minutes'])} min",
        f"- Challenger q50 MAE: {_blank(summary['challenger_q50_mae_minutes'])} min",
        f"- Challenger minus current MAE: {_blank(summary['challenger_minus_current_mae_minutes'])} min",
        f"- Challenger minus active-state MAE: {_blank(summary['challenger_minus_active_state_mae_minutes'])} min",
        f"- Current q10-q90 coverage: {_blank(summary['current_q10_q90_coverage'])}",
        f"- Active-state q10-q90 coverage: {_blank(summary['active_state_q10_q90_coverage'])}",
        f"- Challenger q10-q90 coverage: {_blank(summary['challenger_q10_q90_coverage'])}",
        f"- Current high-error rows: {summary['current_high_error_rows']}",
        f"- Challenger high-error rows: {summary['challenger_high_error_rows']}",
        f"- Tail uplift rows: {summary['tail_uplift_rows']}",
        f"- Challenger gate status: {summary['challenger_gate_status']}",
        "",
        "## Source Mix",
        "",
        "| Source | Rows | Current MAE | Active-state MAE | Challenger MAE | Delta vs current | Current coverage | Challenger coverage | High-error |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in source_segments:
        lines.append(
            "| {source} | {rows} | {current} | {active} | {challenger} | {delta} | {current_cov} | {challenger_cov} | {high} |".format(
                source=row["segment"],
                rows=row["rows"],
                current=row["current_mae"],
                active=row["active_state_mae"],
                challenger=row["challenger_mae"],
                delta=row["mae_delta_challenger_minus_current"],
                current_cov=row["current_coverage"],
                challenger_cov=row["challenger_coverage"],
                high=row["challenger_high_error_rows"],
            )
        )
    lines.extend(
        [
            "",
            "## Biggest Improvements",
            "",
            "| Event | Time | Feeder | Device | Actual | Current p50 | Challenger p50 | Error delta | Source | Tail uplift |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in improvements:
        lines.append(
            "| {ref} | {time} | {feeder} | {device} | {actual} | {current} | {challenger} | {delta} | {source} | {tail} |".format(
                ref=row.get("event_ref", ""),
                time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                device=row.get("device_id", ""),
                actual=row.get("actual_restoration_minutes", ""),
                current=row.get("current_p50", ""),
                challenger=row.get("challenger_p50", ""),
                delta=row.get("error_delta_challenger_minus_current", ""),
                source=row.get("challenger_source", ""),
                tail=row.get("tail_uplift_applied", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Biggest Remaining Misses",
            "",
            "| Event | Time | Feeder | Device | Actual | Challenger p50 | Challenger error | Covered | Source |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in residual:
        lines.append(
            "| {ref} | {time} | {feeder} | {device} | {actual} | {challenger} | {error} | {covered} | {source} |".format(
                ref=row.get("event_ref", ""),
                time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                device=row.get("device_id", ""),
                actual=row.get("actual_restoration_minutes", ""),
                challenger=row.get("challenger_p50", ""),
                error=row.get("challenger_absolute_error", ""),
                covered=row.get("challenger_covered_q10_q90", ""),
                source=row.get("challenger_source", ""),
            )
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
            "- PEA/SFSD/ReportPO quarantine rows are not used in predictions, MAE, coverage, or fallback logic.",
            "- WebEx is used only as trigger/device evidence; AIS outage/restore remains the customer-facing truth.",
            "- This command does not overwrite `runtime/model_quantiles.json` and does not send production AIS notifications.",
            "- Outputs omit source chat bodies, room identifiers, credentials, customer meter identifier lists, and customer identity fields.",
        ]
    )
    return "\n".join(lines) + "\n"


def _recommendation(current_mae: float | None, active_mae: float | None, challenger_mae: float | None, challenger_coverage: float | None) -> str:
    if challenger_mae is None:
        return "No usable AIS-only challenger rows were available; continue shadow capture."
    if challenger_mae <= GATE_Q50_MAE_MAX and challenger_coverage is not None and GATE_COVERAGE_MIN <= challenger_coverage <= GATE_COVERAGE_MAX:
        return "AIS-only remaining-time challenger passes the shadow metric gate; prepare a review package before any production use."
    baseline = active_mae if active_mae is not None else current_mae
    if baseline is not None and challenger_mae < baseline:
        return "AIS-only remaining-time challenger improves the best current shadow baseline but still fails the production gate; use residual misses to request AIS/operation cause and lifecycle fields."
    return "AIS-only remaining-time challenger does not improve enough; prioritize new AIS/operation fields for long-outage cause, crew lifecycle, battery backup, switching, and material repair."


def _load_affected_meters_by_event(db_path: str | Path) -> dict[str, set[str]]:
    path = Path(db_path)
    if not path.exists():
        return {}
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        query = """
            SELECT n.event_id, n.payload_json
            FROM notifications n
            JOIN (
                SELECT event_id, MAX(id) AS max_id
                FROM notifications
                GROUP BY event_id
            ) latest ON latest.max_id = n.id
        """
        return {str(event_id): _affected_meters(payload) for event_id, payload in conn.execute(query).fetchall()}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def _affected_meters(payload_json: str | None) -> set[str]:
    if not payload_json:
        return set()
    try:
        payload = json.loads(payload_json)
    except Exception:
        return set()
    return {
        normalized
        for normalized in (
            _normalize_key(item.get("peano"))
            for item in payload.get("affected_customers") or []
            if isinstance(item, dict)
        )
        if normalized
    }


def _load_truth_intervals(path: str | Path) -> list[TruthInterval]:
    output: list[TruthInterval] = []
    for row in _read_csv(path):
        if str(row.get("truth_quality") or "").strip().upper() != "OK":
            continue
        meter = _normalize_key(row.get("peano"))
        start = _parse_dt(row.get("outage_start_time"))
        restore = _parse_dt(row.get("power_restore_time"))
        actual = _to_float(row.get("actual_restoration_minutes"))
        if not meter or start is None or restore is None or actual is None or actual <= 5 or actual > 1440:
            continue
        output.append(
            TruthInterval(
                meter_id=meter,
                outage_start_time=start,
                power_restore_time=restore,
                actual_restoration_minutes=actual,
            )
        )
    return sorted(output, key=lambda item: item.power_restore_time)


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


def _quantile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _coverage(rows: list[dict[str, str]], column: str) -> float | None:
    values = [str(row.get(column) or "").upper() for row in rows if str(row.get(column) or "").strip()]
    if not values:
        return None
    return sum(1 for value in values if value == "TRUE") / len(values)


def _covered(actual: float | None, lower: float | None, upper: float | None) -> bool | None:
    if actual is None or lower is None or upper is None:
        return None
    return lower <= actual <= upper


def _numbers(rows: list[dict[str, str]], column: str) -> list[float]:
    return [value for value in (_to_float(row.get(column)) for row in rows) if value is not None]


def _mean_or_none(values: list[float]) -> float | None:
    return mean(values) if values else None


def _gate_status(mae: float | None, coverage: float | None) -> str:
    if mae is None or coverage is None:
        return "no_truth"
    if mae <= GATE_Q50_MAE_MAX and GATE_COVERAGE_MIN <= coverage <= GATE_COVERAGE_MAX:
        return "pass"
    return "fail"


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    numeric = _to_float(text)
    if numeric is not None and 20000 <= numeric <= 80000:
        return datetime(1899, 12, 30) + timedelta(days=numeric)
    text = text.replace("T", " ").removesuffix("Z")
    if "." in text:
        head, tail = text.split(".", 1)
        match = re.match(r"\d+", tail)
        if match:
            text = head + "." + match.group(0)[:6]
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ):
        try:
            return _normalize_year(datetime.strptime(text, fmt))
        except ValueError:
            pass
    try:
        return _normalize_year(datetime.fromisoformat(text)).replace(tzinfo=None)
    except ValueError:
        return None


def _normalize_year(value: datetime) -> datetime:
    if value.year > 2400:
        return value.replace(year=value.year - 543, tzinfo=None)
    return value.replace(tzinfo=None)


def _normalize_key(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"", "nan", "none", "null", "nat"}:
        return ""
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return re.sub(r"\s+", "", text).upper()


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    numeric = _to_float(value)
    return int(numeric) if numeric is not None else 0


def _or_zero(value: float | None) -> float:
    return value if value is not None else 0.0


def _round_or_none(value: float | None, *, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _bool_str(value: bool | None) -> str:
    if value is None:
        return ""
    return "TRUE" if value else "FALSE"


def _normalize_bool_text(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"TRUE", "FALSE"}:
        return text
    if text in {"1", "YES", "Y"}:
        return "TRUE"
    if text in {"0", "NO", "N"}:
        return "FALSE"
    return ""


def _fmt(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _blank(value: Any) -> str:
    return "" if value is None else str(value)
