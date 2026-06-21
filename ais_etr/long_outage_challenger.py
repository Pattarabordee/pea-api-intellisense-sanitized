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


LONG_OUTAGE_COLUMNS = (
    "event_id",
    "incident_id",
    "event_time",
    "horizon_minutes",
    "as_of_time",
    "device_type",
    "feeder",
    "affected_count",
    "affected_peano_count",
    "active_alarm_count",
    "active_peano_count",
    "max_active_elapsed_minutes",
    "actual_restoration_minutes",
    "baseline_source",
    "baseline_p50",
    "baseline_q10",
    "baseline_q90",
    "baseline_absolute_error",
    "baseline_covered_q10_q90",
    "refresh_p50",
    "refresh_q10",
    "refresh_q90",
    "refresh_absolute_error",
    "refresh_covered_q10_q90",
    "error_delta_refresh_minus_baseline",
    "refresh_notes",
)


@dataclass(frozen=True)
class AlarmInterval:
    peano: str
    outage_start_time: datetime
    power_restore_time: datetime
    actual_restoration_minutes: float


def build_long_outage_refresh_challenger(
    db_path: str | Path,
    comparison_csv: str | Path,
    ais_truth_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    history_challenger_csv: str | Path | None = None,
    horizons_minutes: tuple[int, ...] = (0, 15, 30, 60, 120),
    min_history_rows: int = 10,
) -> dict[str, Any]:
    if min_history_rows < 1:
        raise ValueError("min_history_rows must be at least 1")
    horizons = tuple(sorted({int(value) for value in horizons_minutes}))
    if any(value < 0 for value in horizons):
        raise ValueError("horizons_minutes must be non-negative")

    comparison_rows = [
        row
        for row in _read_csv(comparison_csv)
        if _to_float(row.get("actual_restoration_minutes")) is not None
    ]
    baseline_by_event = _load_history_baseline(history_challenger_csv)
    peanos_by_event = _load_affected_peanos_by_event(db_path)
    intervals = _load_alarm_intervals(ais_truth_csv)
    intervals_by_peano: dict[str, list[AlarmInterval]] = {}
    for interval in intervals:
        intervals_by_peano.setdefault(interval.peano, []).append(interval)
    for values in intervals_by_peano.values():
        values.sort(key=lambda item: item.outage_start_time)
    intervals = sorted(intervals, key=lambda item: item.outage_start_time)

    rows: list[dict[str, str]] = []
    for comparison in comparison_rows:
        for horizon in horizons:
            rows.append(
                _build_one_row(
                    comparison,
                    baseline_by_event.get(comparison.get("event_id") or "", {}),
                    peanos_by_event.get(comparison.get("event_id") or "", set()),
                    intervals,
                    intervals_by_peano,
                    horizon_minutes=horizon,
                    min_history_rows=min_history_rows,
                )
            )
    _write_csv(output_csv, LONG_OUTAGE_COLUMNS, rows)
    summary = _summary(rows, horizons)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, rows), encoding="utf-8-sig")
    return {
        **summary,
        "db_path": str(db_path),
        "comparison_csv": str(comparison_csv),
        "ais_truth_csv": str(ais_truth_csv),
        "history_challenger_csv": str(history_challenger_csv) if history_challenger_csv else None,
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def _build_one_row(
    row: dict[str, str],
    baseline: dict[str, str],
    affected_peanos: set[str],
    intervals: list[AlarmInterval],
    intervals_by_peano: dict[str, list[AlarmInterval]],
    *,
    horizon_minutes: int,
    min_history_rows: int,
) -> dict[str, str]:
    event_dt = _parse_dt(row.get("event_time"))
    actual = _to_float(row.get("actual_restoration_minutes"))
    base = {column: "" for column in LONG_OUTAGE_COLUMNS}
    base.update(
        {
            "event_id": row.get("event_id", ""),
            "incident_id": row.get("incident_id", ""),
            "event_time": row.get("event_time", ""),
            "horizon_minutes": str(horizon_minutes),
            "device_type": row.get("device_type", ""),
            "feeder": row.get("feeder", ""),
            "affected_count": row.get("affected_count", ""),
            "affected_peano_count": str(len(affected_peanos)),
            "actual_restoration_minutes": _fmt(actual),
        }
    )
    if event_dt is None or actual is None:
        base["refresh_notes"] = "missing event time or actual restoration"
        return base

    as_of = event_dt + timedelta(minutes=horizon_minutes)
    baseline_source = "ais_history" if baseline else "current_model"
    baseline_p50 = _to_float(baseline.get("history_p50")) or _to_float(row.get("current_p50"))
    baseline_q10 = _to_float(baseline.get("history_q10")) or _to_float(row.get("current_q10"))
    baseline_q90 = _to_float(baseline.get("history_q90")) or _to_float(row.get("current_q90"))
    baseline_error = abs(baseline_p50 - actual) if baseline_p50 is not None else None
    active = _active_intervals(affected_peanos, intervals_by_peano, as_of)
    active_peanos = {item.peano for item in active}
    max_elapsed = max(
        ((as_of - item.outage_start_time).total_seconds() / 60 for item in active),
        default=None,
    )
    refresh_p50 = baseline_p50
    refresh_q10 = baseline_q10
    refresh_q90 = baseline_q90
    notes = "no_active_ais_alarm_at_asof"

    if active and max_elapsed is not None:
        affected_prior = [
            item.actual_restoration_minutes
            for peano in affected_peanos
            for item in intervals_by_peano.get(peano, [])
            if item.power_restore_time < event_dt
        ]
        prior_source = "affected_peano_prior"
        if len(affected_prior) < min_history_rows:
            affected_prior = [item.actual_restoration_minutes for item in intervals if item.power_restore_time < event_dt]
            prior_source = "global_prior"
        conditional = [value for value in affected_prior if value >= max_elapsed]
        if len(conditional) < min_history_rows:
            conditional = [
                item.actual_restoration_minutes
                for item in intervals
                if item.power_restore_time < event_dt and item.actual_restoration_minutes >= max_elapsed
            ]
            prior_source = "global_conditional_prior"
        if conditional:
            refresh_p50 = max(_or_zero(baseline_p50), max_elapsed, _quantile(conditional, 0.5))
            refresh_q10 = max(max_elapsed, _quantile(conditional, 0.1))
            refresh_q90 = max(refresh_p50, _quantile(conditional, 0.9))
            notes = f"active_ais_alarm_asof; prior_source={prior_source}; conditional_rows={len(conditional)}"
        else:
            refresh_p50 = max(_or_zero(baseline_p50), max_elapsed)
            refresh_q10 = max_elapsed
            refresh_q90 = max(refresh_p50, _or_zero(baseline_q90))
            notes = "active_ais_alarm_asof; no_conditional_prior"

    refresh_error = abs(refresh_p50 - actual) if refresh_p50 is not None else None
    base.update(
        {
            "as_of_time": as_of.isoformat(timespec="seconds"),
            "active_alarm_count": str(len(active)),
            "active_peano_count": str(len(active_peanos)),
            "max_active_elapsed_minutes": _fmt(max_elapsed),
            "baseline_source": baseline_source,
            "baseline_p50": _fmt(baseline_p50),
            "baseline_q10": _fmt(baseline_q10),
            "baseline_q90": _fmt(baseline_q90),
            "baseline_absolute_error": _fmt(baseline_error),
            "baseline_covered_q10_q90": _bool_str(_covered(actual, baseline_q10, baseline_q90)),
            "refresh_p50": _fmt(refresh_p50),
            "refresh_q10": _fmt(refresh_q10),
            "refresh_q90": _fmt(refresh_q90),
            "refresh_absolute_error": _fmt(refresh_error),
            "refresh_covered_q10_q90": _bool_str(_covered(actual, refresh_q10, refresh_q90)),
            "error_delta_refresh_minus_baseline": _fmt(_delta(refresh_error, baseline_error)),
            "refresh_notes": notes,
        }
    )
    return base


def _summary(rows: list[dict[str, str]], horizons: tuple[int, ...]) -> dict[str, Any]:
    by_horizon: list[dict[str, Any]] = []
    for horizon in horizons:
        group = [row for row in rows if row.get("horizon_minutes") == str(horizon)]
        refresh_errors = _numbers(group, "refresh_absolute_error")
        baseline_errors = _numbers(group, "baseline_absolute_error")
        by_horizon.append(
            {
                "horizon_minutes": horizon,
                "incidents": len(group),
                "active_alarm_incidents": sum(1 for row in group if (_to_float(row.get("active_alarm_count")) or 0) > 0),
                "baseline_q50_mae_minutes": _round_or_none(mean(baseline_errors) if baseline_errors else None),
                "baseline_q10_q90_coverage": _round_or_none(_coverage(group, "baseline_covered_q10_q90"), digits=3),
                "refresh_q50_mae_minutes": _round_or_none(mean(refresh_errors) if refresh_errors else None),
                "refresh_q10_q90_coverage": _round_or_none(_coverage(group, "refresh_covered_q10_q90"), digits=3),
            }
        )
    best = min(
        (item for item in by_horizon if item["refresh_q50_mae_minutes"] is not None),
        key=lambda item: item["refresh_q50_mae_minutes"],
        default=None,
    )
    return {
        "incidents": len({row.get("event_id") for row in rows if row.get("event_id")}),
        "horizons": by_horizon,
        "best_horizon_minutes": best["horizon_minutes"] if best else None,
        "best_refresh_q50_mae_minutes": best["refresh_q50_mae_minutes"] if best else None,
        "best_refresh_q10_q90_coverage": best["refresh_q10_q90_coverage"] if best else None,
        "best_refresh_gate_status": _gate_status(
            best["refresh_q50_mae_minutes"] if best else None,
            best["refresh_q10_q90_coverage"] if best else None,
        ),
    }


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    best_horizon = summary["best_horizon_minutes"]
    residual = [
        row
        for row in rows
        if row.get("horizon_minutes") == str(best_horizon)
        and _to_float(row.get("refresh_absolute_error")) is not None
    ]
    residual = sorted(residual, key=lambda row: _to_float(row.get("refresh_absolute_error")) or 0, reverse=True)[:10]
    active_mix = Counter(
        "active" if (_to_float(row.get("active_alarm_count")) or 0) > 0 else "inactive"
        for row in rows
        if row.get("horizon_minutes") == str(best_horizon)
    )
    lines = [
        "# AIS Long-Outage Refresh Challenger",
        "",
        "This diagnostic simulates refresh-time ETR updates using AIS AC mains alarms that are still active as of the evaluation horizon. It is not an initial-send model and does not expose PEANO lists, raw Webex text, room IDs, tokens, or customer registration names.",
        "",
        "## Horizon Summary",
        "",
        "| Horizon min | Incidents | Active alarm incidents | Baseline MAE | Baseline coverage | Refresh MAE | Refresh coverage |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in summary["horizons"]:
        lines.append(
            f"| {item['horizon_minutes']} | {item['incidents']} | {item['active_alarm_incidents']} | "
            f"{_blank(item['baseline_q50_mae_minutes'])} | {_blank(item['baseline_q10_q90_coverage'])} | "
            f"{_blank(item['refresh_q50_mae_minutes'])} | {_blank(item['refresh_q10_q90_coverage'])} |"
        )
    lines.extend(
        [
            "",
            "## Best Observed Refresh Horizon",
            "",
            f"- Best horizon by MAE: {summary['best_horizon_minutes']} minutes",
            f"- Best refresh MAE: {_blank(summary['best_refresh_q50_mae_minutes'])} minutes",
            f"- Best refresh q10-q90 coverage: {_blank(summary['best_refresh_q10_q90_coverage'])}",
            f"- Gate status: {summary['best_refresh_gate_status']}",
            f"- Active mix at best horizon: {dict(active_mix)}",
            "",
            "## Biggest Remaining Misses At Best Horizon",
            "",
            "| Incident | Event time | Feeder | Actual | Active alarms | Max elapsed | Refresh p50 | Refresh error | Covered |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in residual:
        lines.append(
            "| {incident} | {time} | {feeder} | {actual} | {active} | {elapsed} | {p50} | {error} | {covered} |".format(
                incident=row.get("incident_id") or row.get("event_id") or "",
                time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                actual=row.get("actual_restoration_minutes", ""),
                active=row.get("active_alarm_count", ""),
                elapsed=row.get("max_active_elapsed_minutes", ""),
                p50=row.get("refresh_p50", ""),
                error=row.get("refresh_absolute_error", ""),
                covered=row.get("refresh_covered_q10_q90", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Still-active AIS alarm state is directionally useful, but it does not solve the q50 MAE gate by itself on the current incident set.",
            "- The feature is better suited for scheduled refresh or escalation logic than for the first shadow notification.",
            "- To move toward MAE <= 16, the next feature lane should add operational repair lifecycle or cause/work-type data that can distinguish multi-hour field work before restoration is complete.",
        ]
    )
    return "\n".join(lines) + "\n"


def _active_intervals(
    peanos: set[str],
    intervals_by_peano: dict[str, list[AlarmInterval]],
    as_of: datetime,
) -> list[AlarmInterval]:
    active = []
    for peano in peanos:
        for interval in intervals_by_peano.get(peano, []):
            if interval.outage_start_time <= as_of < interval.power_restore_time:
                active.append(interval)
    return active


def _load_history_baseline(path: str | Path | None) -> dict[str, dict[str, str]]:
    if not path or not Path(path).exists():
        return {}
    rows = _read_csv(path)
    return {row.get("event_id", ""): row for row in rows if row.get("event_id")}


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
        return {str(event_id): _affected_peanos(payload) for event_id, payload in conn.execute(query).fetchall()}
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


def _load_alarm_intervals(path: str | Path) -> list[AlarmInterval]:
    intervals: list[AlarmInterval] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("truth_quality") or "").strip().upper() != "OK":
                continue
            peano = _normalize_key(row.get("peano"))
            start = _parse_dt(row.get("outage_start_time"))
            restore = _parse_dt(row.get("power_restore_time"))
            actual = _to_float(row.get("actual_restoration_minutes"))
            if not peano or start is None or restore is None or actual is None or actual <= 5 or actual > 1440:
                continue
            intervals.append(
                AlarmInterval(
                    peano=peano,
                    outage_start_time=start,
                    power_restore_time=restore,
                    actual_restoration_minutes=actual,
                )
            )
    return intervals


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


def _covered(actual: float, lower: float | None, upper: float | None) -> bool | None:
    if lower is None or upper is None:
        return None
    return lower <= actual <= upper


def _numbers(rows: list[dict[str, str]], column: str) -> list[float]:
    return [value for value in (_to_float(row.get(column)) for row in rows) if value is not None]


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
