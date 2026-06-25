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
from typing import Any

from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN, GATE_Q50_MAE_MAX


ACTIVE_STATE_COLUMNS = (
    "event_id",
    "webex_message_ref",
    "event_time",
    "district",
    "device_type",
    "device_id",
    "feeder",
    "event_age_band",
    "active_elapsed_minutes",
    "remaining_actual_minutes",
    "affected_count",
    "affected_meter_count",
    "current_p50",
    "current_q10",
    "current_q90",
    "current_absolute_error",
    "current_covered_q10_q90",
    "active_source",
    "active_rows_used",
    "active_p50",
    "active_q10",
    "active_q90",
    "active_absolute_error",
    "active_covered_q10_q90",
    "error_delta_active_minus_current",
    "active_notes",
)

SEGMENT_COLUMNS = (
    "dimension",
    "segment",
    "rows",
    "current_mae",
    "active_mae",
    "mae_delta_active_minus_current",
    "current_coverage",
    "active_coverage",
    "high_error_rows",
)


@dataclass(frozen=True)
class TruthInterval:
    meter_id: str
    outage_start_time: datetime
    power_restore_time: datetime
    actual_restoration_minutes: float


def build_active_state_remaining_challenger(
    db_path: str | Path,
    readiness_csv: str | Path,
    ais_truth_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    segments_output: str | Path | None = None,
    *,
    min_segment_rows: int = 5,
    min_meter_history_rows: int = 3,
    high_error_minutes: float = 60.0,
) -> dict[str, Any]:
    if min_segment_rows < 1:
        raise ValueError("min_segment_rows must be at least 1")
    if min_meter_history_rows < 1:
        raise ValueError("min_meter_history_rows must be at least 1")

    readiness_rows = [
        row
        for row in _read_csv(readiness_csv)
        if row.get("notification_time_gate") == "shadow_etr_candidate"
        and row.get("active_ais_outage_confirmed") == "TRUE"
        and _to_float(row.get("remaining_actual_minutes")) is not None
    ]
    readiness_rows = sorted(readiness_rows, key=lambda row: _parse_dt(row.get("event_time")) or datetime.max)
    meters_by_event = _load_affected_meters_by_event(db_path)
    intervals = _load_truth_intervals(ais_truth_csv)

    output_rows: list[dict[str, str]] = []
    prior_rows: list[dict[str, str]] = []
    for row in readiness_rows:
        prediction = _predict_active_remaining(
            row,
            prior_rows,
            meters_by_event.get(row.get("event_id") or "", set()),
            intervals,
            min_segment_rows=min_segment_rows,
            min_meter_history_rows=min_meter_history_rows,
        )
        output_rows.append(prediction)
        prior_rows.append(prediction)

    _write_csv(output_csv, ACTIVE_STATE_COLUMNS, output_rows)
    segments = _build_segments(output_rows, high_error_minutes)
    if segments_output:
        _write_csv(segments_output, SEGMENT_COLUMNS, segments)
    summary = _summary(output_rows, segments, min_segment_rows, min_meter_history_rows, high_error_minutes)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, output_rows, segments), encoding="utf-8-sig")
    return {
        **summary,
        "db_path": str(db_path),
        "readiness_csv": str(readiness_csv),
        "ais_truth_csv": str(ais_truth_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "segments_output": str(segments_output) if segments_output else None,
    }


def _predict_active_remaining(
    row: dict[str, str],
    prior_rows: list[dict[str, str]],
    affected_meters: set[str],
    intervals: list[TruthInterval],
    *,
    min_segment_rows: int,
    min_meter_history_rows: int,
) -> dict[str, str]:
    event_dt = _parse_dt(row.get("event_time"))
    elapsed = _to_float(row.get("max_elapsed_since_ais_start_minutes"))
    actual = _to_float(row.get("remaining_actual_minutes"))
    current_p50 = _to_float(row.get("current_p50"))
    current_q10 = _to_float(row.get("current_q10"))
    current_q90 = _to_float(row.get("current_q90"))
    current_error = abs(current_p50 - actual) if current_p50 is not None and actual is not None else None
    selected, source, notes = _select_prior_values(
        row,
        prior_rows,
        affected_meters,
        intervals,
        event_dt,
        elapsed,
        min_segment_rows=min_segment_rows,
        min_meter_history_rows=min_meter_history_rows,
    )

    active_p50 = current_p50
    active_q10 = current_q10
    active_q90 = current_q90
    if selected:
        prior_p50 = _quantile(selected, 0.5)
        prior_q10 = _quantile(selected, 0.1)
        prior_q90 = _quantile(selected, 0.9)
        if source in {"prior_same_device_remaining", "prior_same_feeder_remaining", "prior_shadow_remaining_global"}:
            active_p50 = max(_or_zero(current_p50), prior_p50)
        else:
            active_p50 = current_p50
        active_q10 = max(0.0, min(active_p50, prior_q10))
        active_q90 = max(_or_zero(current_q90), active_p50, prior_q90)
    active_error = abs(active_p50 - actual) if active_p50 is not None and actual is not None else None

    return {
        "event_id": row.get("event_id", ""),
        "webex_message_ref": row.get("webex_message_ref", ""),
        "event_time": row.get("event_time", ""),
        "district": row.get("district", ""),
        "device_type": row.get("device_type", ""),
        "device_id": row.get("device_id", ""),
        "feeder": row.get("feeder", ""),
        "event_age_band": row.get("event_age_band", ""),
        "active_elapsed_minutes": _fmt(elapsed),
        "remaining_actual_minutes": _fmt(actual),
        "affected_count": row.get("affected_count", ""),
        "affected_meter_count": str(len(affected_meters)),
        "current_p50": _fmt(current_p50),
        "current_q10": _fmt(current_q10),
        "current_q90": _fmt(current_q90),
        "current_absolute_error": _fmt(current_error),
        "current_covered_q10_q90": _bool_str(_covered(actual, current_q10, current_q90)),
        "active_source": source,
        "active_rows_used": str(len(selected)),
        "active_p50": _fmt(active_p50),
        "active_q10": _fmt(active_q10),
        "active_q90": _fmt(active_q90),
        "active_absolute_error": _fmt(active_error),
        "active_covered_q10_q90": _bool_str(_covered(actual, active_q10, active_q90)),
        "error_delta_active_minus_current": _fmt(_delta(active_error, current_error)),
        "active_notes": notes,
    }


def _select_prior_values(
    row: dict[str, str],
    prior_rows: list[dict[str, str]],
    affected_meters: set[str],
    intervals: list[TruthInterval],
    event_dt: datetime | None,
    elapsed: float | None,
    *,
    min_segment_rows: int,
    min_meter_history_rows: int,
) -> tuple[list[float], str, str]:
    device = str(row.get("device_id") or "").strip().upper()
    feeder = str(row.get("feeder") or "").strip().upper()
    device_values = [
        value
        for prior in prior_rows
        if str(prior.get("device_id") or "").strip().upper() == device
        if (value := _to_float(prior.get("remaining_actual_minutes"))) is not None
    ]
    if len(device_values) >= min_segment_rows:
        return device_values, "prior_same_device_remaining", f"device_prior_rows={len(device_values)}"

    feeder_values = [
        value
        for prior in prior_rows
        if str(prior.get("feeder") or "").strip().upper() == feeder
        if (value := _to_float(prior.get("remaining_actual_minutes"))) is not None
    ]
    if len(feeder_values) >= min_segment_rows:
        return feeder_values, "prior_same_feeder_remaining", f"feeder_prior_rows={len(feeder_values)}"

    if event_dt is not None and elapsed is not None and affected_meters:
        affected_values = [
            interval.actual_restoration_minutes - elapsed
            for interval in intervals
            if interval.meter_id in affected_meters
            and interval.power_restore_time < event_dt
            and interval.actual_restoration_minutes >= elapsed
        ]
        if len(affected_values) >= min_meter_history_rows:
            return affected_values, "affected_meter_conditional_duration_prior", f"affected_meter_prior_rows={len(affected_values)}"

    if event_dt is not None and elapsed is not None:
        global_values = [
            interval.actual_restoration_minutes - elapsed
            for interval in intervals
            if interval.power_restore_time < event_dt and interval.actual_restoration_minutes >= elapsed
        ]
        if global_values:
            return global_values, "global_conditional_duration_prior", f"global_conditional_rows={len(global_values)}"

    if prior_rows:
        global_prior = [
            value
            for prior in prior_rows
            if (value := _to_float(prior.get("remaining_actual_minutes"))) is not None
        ]
        if global_prior:
            return global_prior, "prior_shadow_remaining_global", f"prior_shadow_rows={len(global_prior)}"

    return [], "current_model_only", "no_time_respecting_prior_available"


def _build_segments(rows: list[dict[str, str]], high_error_minutes: float) -> list[dict[str, str]]:
    output = []
    for dimension in ("active_source", "feeder", "device_id", "event_age_band"):
        groups: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            groups.setdefault(row.get(dimension) or "<blank>", []).append(row)
        for segment, values in groups.items():
            output.append(_segment_row(dimension, segment, values, high_error_minutes))
    return sorted(output, key=lambda row: (row["dimension"], -_to_int(row["rows"]), row["segment"]))


def _segment_row(dimension: str, segment: str, rows: list[dict[str, str]], high_error_minutes: float) -> dict[str, str]:
    current_errors = _numbers(rows, "current_absolute_error")
    active_errors = _numbers(rows, "active_absolute_error")
    current_mae = mean(current_errors) if current_errors else None
    active_mae = mean(active_errors) if active_errors else None
    return {
        "dimension": dimension,
        "segment": segment,
        "rows": str(len(rows)),
        "current_mae": _fmt(current_mae),
        "active_mae": _fmt(active_mae),
        "mae_delta_active_minus_current": _fmt(_delta(active_mae, current_mae)),
        "current_coverage": _fmt(_coverage(rows, "current_covered_q10_q90"), digits=3),
        "active_coverage": _fmt(_coverage(rows, "active_covered_q10_q90"), digits=3),
        "high_error_rows": str(sum(1 for value in active_errors if value >= high_error_minutes)),
    }


def _summary(
    rows: list[dict[str, str]],
    segments: list[dict[str, str]],
    min_segment_rows: int,
    min_meter_history_rows: int,
    high_error_minutes: float,
) -> dict[str, Any]:
    current_errors = _numbers(rows, "current_absolute_error")
    active_errors = _numbers(rows, "active_absolute_error")
    current_mae = mean(current_errors) if current_errors else None
    active_mae = mean(active_errors) if active_errors else None
    current_coverage = _coverage(rows, "current_covered_q10_q90")
    active_coverage = _coverage(rows, "active_covered_q10_q90")
    source_counts = Counter(row.get("active_source") or "<blank>" for row in rows)
    return {
        "candidates": len(rows),
        "current_q50_mae_minutes": _round_or_none(current_mae),
        "current_q10_q90_coverage": _round_or_none(current_coverage, digits=3),
        "active_q50_mae_minutes": _round_or_none(active_mae),
        "active_q10_q90_coverage": _round_or_none(active_coverage, digits=3),
        "active_minus_current_mae_minutes": _round_or_none(_delta(active_mae, current_mae)),
        "current_high_error_rows": sum(1 for value in current_errors if value >= high_error_minutes),
        "active_high_error_rows": sum(1 for value in active_errors if value >= high_error_minutes),
        "active_source_counts": dict(source_counts.most_common()),
        "min_segment_rows": min_segment_rows,
        "min_meter_history_rows": min_meter_history_rows,
        "high_error_minutes": high_error_minutes,
        "active_gate_status": _gate_status(active_mae, active_coverage),
        "recommendation": _recommendation(current_mae, active_mae, active_coverage),
    }


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]], segments: list[dict[str, str]]) -> str:
    source_segments = [row for row in segments if row.get("dimension") == "active_source"]
    top_improvements = sorted(
        [row for row in rows if _to_float(row.get("error_delta_active_minus_current")) is not None],
        key=lambda row: _to_float(row.get("error_delta_active_minus_current")) or 0,
    )[:10]
    residual = sorted(
        [row for row in rows if _to_float(row.get("active_absolute_error")) is not None],
        key=lambda row: _to_float(row.get("active_absolute_error")) or 0,
        reverse=True,
    )[:10]
    lines = [
        "# AIS Active-State Remaining Challenger",
        "",
        "This report tests a shadow-only challenger for remaining restoration minutes when AIS confirms the site is still in an active outage at Webex notification time.",
        "",
        "## Summary",
        "",
        f"- Candidate notifications: {summary['candidates']}",
        f"- Current q50 MAE: {_blank(summary['current_q50_mae_minutes'])} min",
        f"- Active-state q50 MAE: {_blank(summary['active_q50_mae_minutes'])} min",
        f"- Active minus current MAE: {_blank(summary['active_minus_current_mae_minutes'])} min",
        f"- Current q10-q90 coverage: {_blank(summary['current_q10_q90_coverage'])}",
        f"- Active-state q10-q90 coverage: {_blank(summary['active_q10_q90_coverage'])}",
        f"- Current high-error rows: {summary['current_high_error_rows']}",
        f"- Active-state high-error rows: {summary['active_high_error_rows']}",
        f"- Active-state gate status: {summary['active_gate_status']}",
        "",
        "## Source Mix",
        "",
        "| Source | Rows | Current MAE | Active MAE | Delta | Current coverage | Active coverage | High-error |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in source_segments:
        lines.append(
            "| {source} | {rows} | {current} | {active} | {delta} | {current_cov} | {active_cov} | {high} |".format(
                source=row["segment"],
                rows=row["rows"],
                current=row["current_mae"],
                active=row["active_mae"],
                delta=row["mae_delta_active_minus_current"],
                current_cov=row["current_coverage"],
                active_cov=row["active_coverage"],
                high=row["high_error_rows"],
            )
        )
    lines.extend(
        [
            "",
            "## Biggest Improvements",
            "",
            "| Event ref | Time | Feeder | Device | Elapsed | Remaining actual | Current p50 | Active p50 | Error delta | Source |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in top_improvements:
        lines.append(
            "| {ref} | {time} | {feeder} | {device} | {elapsed} | {actual} | {current} | {active} | {delta} | {source} |".format(
                ref=row.get("webex_message_ref", ""),
                time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                device=row.get("device_id", ""),
                elapsed=row.get("active_elapsed_minutes", ""),
                actual=row.get("remaining_actual_minutes", ""),
                current=row.get("current_p50", ""),
                active=row.get("active_p50", ""),
                delta=row.get("error_delta_active_minus_current", ""),
                source=row.get("active_source", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Biggest Remaining Misses",
            "",
            "| Event ref | Time | Feeder | Device | Elapsed | Remaining actual | Active p50 | Active error | Covered | Source |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in residual:
        lines.append(
            "| {ref} | {time} | {feeder} | {device} | {elapsed} | {actual} | {active} | {error} | {covered} | {source} |".format(
                ref=row.get("webex_message_ref", ""),
                time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                device=row.get("device_id", ""),
                elapsed=row.get("active_elapsed_minutes", ""),
                actual=row.get("remaining_actual_minutes", ""),
                active=row.get("active_p50", ""),
                error=row.get("active_absolute_error", ""),
                covered=row.get("active_covered_q10_q90", ""),
                source=row.get("active_source", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            str(summary["recommendation"]),
            "",
            "## Safety Notes",
            "",
            "- Outputs use redacted event refs plus device, feeder, timing, and aggregate counts only.",
            "- Outputs omit source chat bodies, room identifiers, credentials, meter identifier lists, and customer identity fields.",
        ]
    )
    return "\n".join(lines) + "\n"


def _recommendation(current_mae: float | None, active_mae: float | None, active_coverage: float | None) -> str:
    if current_mae is None or active_mae is None:
        return "No usable active AIS candidate rows were available; continue shadow capture."
    if active_mae <= GATE_Q50_MAE_MAX and active_coverage is not None and GATE_COVERAGE_MIN <= active_coverage <= GATE_COVERAGE_MAX:
        return "Active-state remaining prediction passes the shadow gate; keep it as a challenger and require source-owner review before any production send."
    if active_mae < current_mae:
        return "Active-state remaining prediction improves MAE, but it still fails the production gate; use it as a shadow challenger and add lifecycle/cause features next."
    return "Active-state remaining prediction does not improve the current baseline enough; prioritize operational lifecycle/cause features before model tuning."


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
    return sorted(output, key=lambda item: item.outage_start_time)


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    if not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: str | Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _quantile(values: list[float], quantile: float) -> float:
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
    return [value for row in rows if (value := _to_float(row.get(column))) is not None]


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


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
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


def _round_or_none(value: float | None, *, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _or_zero(value: float | None) -> float:
    return value if value is not None else 0.0


def _bool_str(value: bool | None) -> str:
    if value is None:
        return ""
    return "TRUE" if value else "FALSE"


def _fmt(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _blank(value: Any) -> str:
    return "" if value is None else str(value)
