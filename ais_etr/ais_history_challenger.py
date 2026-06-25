from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sqlite3
from statistics import mean
from typing import Any

from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN, GATE_Q50_MAE_MAX


AIS_HISTORY_COLUMNS = (
    "event_id",
    "incident_id",
    "event_time",
    "district",
    "device_type",
    "feeder",
    "affected_count",
    "affected_peano_count",
    "actual_restoration_minutes",
    "current_p50",
    "current_absolute_error",
    "current_covered_q10_q90",
    "history_source",
    "history_rows_used",
    "history_p50",
    "history_q10",
    "history_q90",
    "history_absolute_error",
    "history_covered_q10_q90",
    "calibrated_lower_quantile",
    "calibrated_upper_quantile",
    "history_interval_lower",
    "history_interval_upper",
    "history_covered_calibrated_interval",
    "error_delta_history_minus_current",
    "history_notes",
)


@dataclass(frozen=True)
class HistoryTruthRow:
    peano: str
    outage_start_time: datetime
    power_restore_time: datetime
    actual_restoration_minutes: float


def build_ais_history_challenger(
    db_path: str | Path,
    comparison_csv: str | Path,
    ais_truth_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    min_history_rows: int = 10,
    lower_quantile: float = 0.05,
    upper_quantile: float = 0.95,
) -> dict[str, Any]:
    if min_history_rows < 1:
        raise ValueError("min_history_rows must be at least 1")
    _validate_quantile_pair(lower_quantile, upper_quantile)

    comparison_rows = [
        row
        for row in _read_csv(comparison_csv)
        if _to_float(row.get("actual_restoration_minutes")) is not None
    ]
    history_rows = _load_history_rows(ais_truth_csv)
    peanos_by_event = _load_affected_peanos_by_event(db_path)

    output_rows = [
        _build_one_row(
            row,
            history_rows,
            peanos_by_event.get(row.get("event_id") or "", set()),
            min_history_rows=min_history_rows,
            lower_quantile=lower_quantile,
            upper_quantile=upper_quantile,
        )
        for row in comparison_rows
    ]
    _write_csv(output_csv, AIS_HISTORY_COLUMNS, output_rows)
    summary = _summary(output_rows, min_history_rows, lower_quantile, upper_quantile)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, output_rows), encoding="utf-8-sig")
    return {
        **summary,
        "db_path": str(db_path),
        "comparison_csv": str(comparison_csv),
        "ais_truth_csv": str(ais_truth_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def _build_one_row(
    row: dict[str, str],
    history_rows: list[HistoryTruthRow],
    affected_peanos: set[str],
    *,
    min_history_rows: int,
    lower_quantile: float,
    upper_quantile: float,
) -> dict[str, str]:
    event_dt = _parse_dt(row.get("event_time"))
    actual = _to_float(row.get("actual_restoration_minutes"))
    current_p50 = _to_float(row.get("current_p50"))
    current_error = _to_float(row.get("current_absolute_error"))
    base = {column: "" for column in AIS_HISTORY_COLUMNS}
    base.update(
        {
            "event_id": row.get("event_id", ""),
            "incident_id": row.get("incident_id", ""),
            "event_time": row.get("event_time", ""),
            "district": row.get("district", ""),
            "device_type": row.get("device_type", ""),
            "feeder": row.get("feeder", ""),
            "affected_count": row.get("affected_count", ""),
            "affected_peano_count": str(len(affected_peanos)),
            "actual_restoration_minutes": _fmt(actual),
            "current_p50": row.get("current_p50", ""),
            "current_absolute_error": row.get("current_absolute_error", ""),
            "current_covered_q10_q90": row.get("current_covered_q10_q90", ""),
            "calibrated_lower_quantile": _fmt(lower_quantile, digits=2),
            "calibrated_upper_quantile": _fmt(upper_quantile, digits=2),
        }
    )
    if event_dt is None or actual is None:
        base["history_notes"] = "missing event time or actual restoration"
        return base

    prior_rows = [candidate for candidate in history_rows if candidate.power_restore_time < event_dt]
    affected_history = [
        candidate
        for candidate in prior_rows
        if candidate.peano and candidate.peano in affected_peanos
    ]
    if len(affected_history) >= min_history_rows:
        selected = affected_history
        source = "affected_peano_history"
        fallback = ""
    else:
        selected = prior_rows
        source = "global_prior"
        fallback = f"affected_history_rows={len(affected_history)} below min_history_rows={min_history_rows}"

    if not selected:
        base.update({"history_source": "no_prior_history", "history_notes": "no prior AIS rows before event time"})
        return base

    values = [candidate.actual_restoration_minutes for candidate in selected]
    history_p50 = _quantile(values, 0.5)
    history_q10 = _quantile(values, 0.1)
    history_q90 = _quantile(values, 0.9)
    history_lower = _quantile(values, lower_quantile)
    history_upper = _quantile(values, upper_quantile)
    history_error = abs(history_p50 - actual)
    base.update(
        {
            "history_source": source,
            "history_rows_used": str(len(values)),
            "history_p50": _fmt(history_p50),
            "history_q10": _fmt(history_q10),
            "history_q90": _fmt(history_q90),
            "history_absolute_error": _fmt(history_error),
            "history_covered_q10_q90": _bool_str(history_q10 <= actual <= history_q90),
            "history_interval_lower": _fmt(history_lower),
            "history_interval_upper": _fmt(history_upper),
            "history_covered_calibrated_interval": _bool_str(history_lower <= actual <= history_upper),
            "error_delta_history_minus_current": _fmt(_delta(history_error, current_error)),
            "history_notes": fallback or "time_respecting_prior_only",
        }
    )
    if current_p50 is None:
        base["history_notes"] = (base["history_notes"] + "; missing current p50").strip("; ")
    return base


def _summary(
    rows: list[dict[str, str]],
    min_history_rows: int,
    lower_quantile: float,
    upper_quantile: float,
) -> dict[str, Any]:
    current_errors = _numbers(rows, "current_absolute_error")
    history_errors = _numbers(rows, "history_absolute_error")
    summary = {
        "incidents": len(rows),
        "history_usable_incidents": len(history_errors),
        "min_history_rows": min_history_rows,
        "history_interval_quantiles": [lower_quantile, upper_quantile],
        "current_q50_mae_minutes": _round_or_none(mean(current_errors) if current_errors else None),
        "current_q10_q90_coverage": _round_or_none(_coverage(rows, "current_covered_q10_q90"), digits=3),
        "history_q50_mae_minutes": _round_or_none(mean(history_errors) if history_errors else None),
        "history_q10_q90_coverage": _round_or_none(_coverage(rows, "history_covered_q10_q90"), digits=3),
        "history_calibrated_interval_coverage": _round_or_none(
            _coverage(rows, "history_covered_calibrated_interval"),
            digits=3,
        ),
        "history_source_counts": dict(Counter(row.get("history_source") or "<blank>" for row in rows)),
    }
    summary["current_gate_status"] = _gate_status(
        summary["current_q50_mae_minutes"],
        summary["current_q10_q90_coverage"],
    )
    summary["history_gate_status"] = _gate_status(
        summary["history_q50_mae_minutes"],
        summary["history_q10_q90_coverage"],
    )
    return summary


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lower, upper = summary["history_interval_quantiles"]
    source_counts = summary["history_source_counts"]
    duration_segments = _history_duration_segments(rows)
    top_improvements = sorted(
        [row for row in rows if _to_float(row.get("error_delta_history_minus_current")) is not None],
        key=lambda row: _to_float(row.get("error_delta_history_minus_current")) or 0,
    )[:10]
    top_residual = sorted(
        [row for row in rows if _to_float(row.get("history_absolute_error")) is not None],
        key=lambda row: _to_float(row.get("history_absolute_error")) or 0,
        reverse=True,
    )[:10]
    lines = [
        "# AIS History Challenger Diagnostic",
        "",
        "This report tests a time-respecting AIS alarm-history challenger. For each incident it uses only AIS truth rows before the Webex event time. It does not expose PEANO lists, raw Webex text, room IDs, tokens, or customer registration names.",
        "",
        "## Summary",
        "",
        f"- Incidents with AIS truth: {summary['incidents']}",
        f"- Incidents with usable prior history: {summary['history_usable_incidents']}",
        f"- Min affected-site history rows before fallback: {summary['min_history_rows']}",
        f"- Current q50 MAE: {_blank(summary['current_q50_mae_minutes'])} min",
        f"- Current q10-q90 coverage: {_blank(summary['current_q10_q90_coverage'])}",
        f"- History q50 MAE: {_blank(summary['history_q50_mae_minutes'])} min",
        f"- History q10-q90 coverage: {_blank(summary['history_q10_q90_coverage'])}",
        f"- History calibrated q{int(lower * 100):02d}-q{int(upper * 100):02d} coverage: {_blank(summary['history_calibrated_interval_coverage'])}",
        f"- Current gate status: {summary['current_gate_status']}",
        f"- History q10-q90 gate status: {summary['history_gate_status']}",
        "",
        "## History Source Mix",
        "",
        "| Source | Incidents |",
        "| --- | ---: |",
    ]
    for source, count in sorted(source_counts.items()):
        lines.append(f"| {source} | {count} |")
    lines.extend(
        [
            "",
            "## Residual Error By Actual Duration",
            "",
            "| Duration band | Incidents | Mean actual | History mean error | Share of history error | History q10-q90 coverage | Calibrated interval coverage |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for segment in duration_segments:
        lines.append(
            f"| {segment['duration_band']} | {segment['incidents']} | {segment['mean_actual_minutes']} | "
            f"{segment['mean_history_error_minutes']} | {segment['share_of_history_error']} | "
            f"{segment['history_q10_q90_coverage']} | {segment['history_calibrated_interval_coverage']} |"
        )
    lines.extend(
        [
            "",
            "## Biggest Error Improvements",
            "",
            "| Incident | Event time | Feeder | Actual | Current p50 | History p50 | Error delta | Source |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in top_improvements:
        lines.append(
            "| {incident} | {time} | {feeder} | {actual} | {current} | {history} | {delta} | {source} |".format(
                incident=row.get("incident_id") or row.get("event_id") or "",
                time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                actual=row.get("actual_restoration_minutes", ""),
                current=row.get("current_p50", ""),
                history=row.get("history_p50", ""),
                delta=row.get("error_delta_history_minus_current", ""),
                source=row.get("history_source", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Biggest Remaining History Misses",
            "",
            "| Incident | Event time | Feeder | Actual | History p50 | History error | q10-q90 covered | Calibrated covered |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in top_residual:
        lines.append(
            "| {incident} | {time} | {feeder} | {actual} | {history} | {error} | {covered} | {calibrated} |".format(
                incident=row.get("incident_id") or row.get("event_id") or "",
                time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                actual=row.get("actual_restoration_minutes", ""),
                history=row.get("history_p50", ""),
                error=row.get("history_absolute_error", ""),
                covered=row.get("history_covered_q10_q90", ""),
                calibrated=row.get("history_covered_calibrated_interval", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- AIS history is useful as a challenger signal, especially for interval calibration, but it is still not enough to meet the q50 MAE gate by itself.",
            "- The calibrated interval is reported separately from the production q10-q90 gate because it may use wider quantiles.",
            "- The next high-value work is long-outage detection: live AIS alarm still-open state, cause/work type, crew lifecycle, weather, and device topology features.",
        ]
    )
    return "\n".join(lines) + "\n"


def _history_duration_segments(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        actual = _to_float(row.get("actual_restoration_minutes"))
        history_error = _to_float(row.get("history_absolute_error"))
        if actual is None or history_error is None:
            continue
        groups.setdefault(_duration_band(actual), []).append(row)
    total_error = sum(_to_float(row.get("history_absolute_error")) or 0 for values in groups.values() for row in values)
    output = []
    for band in ("5-15", "15-60", "60-180", ">180"):
        values = groups.get(band, [])
        if not values:
            continue
        actual_values = [_to_float(row.get("actual_restoration_minutes")) or 0 for row in values]
        errors = [_to_float(row.get("history_absolute_error")) or 0 for row in values]
        q10_values = [row.get("history_covered_q10_q90") or "" for row in values if row.get("history_covered_q10_q90")]
        calibrated_values = [
            row.get("history_covered_calibrated_interval") or ""
            for row in values
            if row.get("history_covered_calibrated_interval")
        ]
        segment_error = sum(errors)
        output.append(
            {
                "duration_band": band,
                "incidents": str(len(values)),
                "mean_actual_minutes": _fmt(mean(actual_values)),
                "mean_history_error_minutes": _fmt(mean(errors)),
                "share_of_history_error": _fmt(segment_error / total_error if total_error else 0, digits=3),
                "history_q10_q90_coverage": _fmt(_bool_coverage(q10_values), digits=3),
                "history_calibrated_interval_coverage": _fmt(_bool_coverage(calibrated_values), digits=3),
            }
        )
    return output


def _duration_band(value: float) -> str:
    if value <= 15:
        return "5-15"
    if value <= 60:
        return "15-60"
    if value <= 180:
        return "60-180"
    return ">180"


def _bool_coverage(values: list[str]) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if str(value).strip().upper() == "TRUE") / len(values)


def _load_affected_peanos_by_event(db_path: str | Path) -> dict[str, set[str]]:
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
        output: dict[str, set[str]] = {}
        for event_id, payload_json in conn.execute(query).fetchall():
            output[str(event_id)] = _affected_peanos(payload_json)
        return output
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def _affected_peanos(payload_json: str | None) -> set[str]:
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


def _load_history_rows(path: str | Path) -> list[HistoryTruthRow]:
    rows: list[HistoryTruthRow] = []
    source = Path(path)
    with source.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            quality = str(row.get("truth_quality") or "").strip().upper()
            if quality and quality != "OK":
                continue
            outage_dt = _parse_dt(row.get("outage_start_time"))
            restore_dt = _parse_dt(row.get("power_restore_time"))
            actual = _to_float(row.get("actual_restoration_minutes"))
            peano = _normalize_key(row.get("peano"))
            if not peano or outage_dt is None or restore_dt is None or actual is None or actual <= 5 or actual > 1440:
                continue
            rows.append(
                HistoryTruthRow(
                    peano=peano,
                    outage_start_time=outage_dt,
                    power_restore_time=restore_dt,
                    actual_restoration_minutes=actual,
                )
            )
    return sorted(rows, key=lambda item: item.outage_start_time)


def _read_csv(path: str | Path) -> list[dict[str, str]]:
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


def _numbers(rows: list[dict[str, str]], column: str) -> list[float]:
    return [value for value in (_to_float(row.get(column)) for row in rows) if value is not None]


def _gate_status(mae: float | None, coverage: float | None) -> str:
    if mae is None or coverage is None:
        return "no_truth"
    if mae <= GATE_Q50_MAE_MAX and GATE_COVERAGE_MIN <= coverage <= GATE_COVERAGE_MAX:
        return "pass"
    return "fail"


def _validate_quantile_pair(lower: float, upper: float) -> None:
    if not (0 <= lower < 0.5 < upper <= 1):
        raise ValueError("lower_quantile and upper_quantile must satisfy 0 <= lower < 0.5 < upper <= 1")


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


def _round_or_none(value: float | None, *, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _bool_str(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def _fmt(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _blank(value: Any) -> str:
    return "" if value is None else str(value)
