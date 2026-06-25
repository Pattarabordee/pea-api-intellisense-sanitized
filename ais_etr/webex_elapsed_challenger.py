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


WEBEX_ELAPSED_COLUMNS = (
    "event_id",
    "incident_id",
    "first_event_time",
    "refresh_event_time",
    "event_count",
    "eligible_refresh_event_count",
    "latest_eligible_elapsed_minutes",
    "district",
    "device_type",
    "feeder",
    "affected_count",
    "affected_peano_count",
    "actual_restoration_minutes",
    "current_p50",
    "current_q10",
    "current_q90",
    "current_absolute_error",
    "current_covered_q10_q90",
    "history_p50",
    "history_q10",
    "history_q90",
    "history_absolute_error",
    "history_covered_q10_q90",
    "refresh_p50",
    "refresh_q10",
    "refresh_q90",
    "refresh_absolute_error",
    "refresh_covered_q10_q90",
    "error_delta_refresh_minus_history",
    "refresh_source",
    "refresh_notes",
)


@dataclass(frozen=True)
class TruthInterval:
    peano: str
    outage_start_time: datetime
    power_restore_time: datetime
    actual_restoration_minutes: float


def build_webex_elapsed_refresh_challenger(
    db_path: str | Path,
    comparison_csv: str | Path,
    audit_csv: str | Path,
    ais_truth_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    history_challenger_csv: str | Path | None = None,
    min_history_rows: int = 10,
    post_restore_tolerance_minutes: float = 5.0,
) -> dict[str, Any]:
    if min_history_rows < 1:
        raise ValueError("min_history_rows must be at least 1")
    if post_restore_tolerance_minutes < 0:
        raise ValueError("post_restore_tolerance_minutes must be non-negative")

    comparison_rows = [
        row
        for row in _read_csv(comparison_csv)
        if _to_float(row.get("actual_restoration_minutes")) is not None
    ]
    message_by_event = _load_message_by_event(db_path)
    cluster_by_message = _load_cluster_by_message(audit_csv)
    grouped = _group_comparison_rows(comparison_rows, message_by_event, cluster_by_message)
    history_by_event = _load_history_baseline(history_challenger_csv)
    peanos_by_event = _load_affected_peanos_by_event(db_path)
    truth_intervals = _load_truth_intervals(ais_truth_csv)

    rows = [
        _build_one_row(
            cluster_id,
            cluster_rows,
            history_by_event,
            peanos_by_event,
            truth_intervals,
            min_history_rows=min_history_rows,
            post_restore_tolerance_minutes=post_restore_tolerance_minutes,
        )
        for cluster_id, cluster_rows in sorted(grouped.items(), key=lambda item: _cluster_sort_key(item[1]))
    ]
    _write_csv(output_csv, WEBEX_ELAPSED_COLUMNS, rows)
    summary = _summary(rows, min_history_rows, post_restore_tolerance_minutes)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, rows), encoding="utf-8-sig")
    return {
        **summary,
        "db_path": str(db_path),
        "comparison_csv": str(comparison_csv),
        "audit_csv": str(audit_csv),
        "ais_truth_csv": str(ais_truth_csv),
        "history_challenger_csv": str(history_challenger_csv) if history_challenger_csv else None,
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def _build_one_row(
    cluster_id: str,
    cluster_rows: list[dict[str, str]],
    history_by_event: dict[str, dict[str, str]],
    peanos_by_event: dict[str, set[str]],
    truth_intervals: list[TruthInterval],
    *,
    min_history_rows: int,
    post_restore_tolerance_minutes: float,
) -> dict[str, str]:
    rows = sorted(cluster_rows, key=lambda row: (_parse_dt(row.get("event_time")) or datetime.max, row.get("event_id") or ""))
    first = rows[0]
    first_dt = _parse_dt(first.get("event_time"))
    actual_values = [_to_float(row.get("actual_restoration_minutes")) for row in rows]
    actual = max(value for value in actual_values if value is not None)
    affected_peanos = peanos_by_event.get(first.get("event_id") or "", set())
    base = {column: "" for column in WEBEX_ELAPSED_COLUMNS}
    base.update(
        {
            "event_id": first.get("event_id", ""),
            "incident_id": cluster_id,
            "first_event_time": first.get("event_time", ""),
            "event_count": str(len(rows)),
            "district": first.get("district", ""),
            "device_type": _join_limited(_unique_values(rows, "device_type")),
            "feeder": _join_limited(_unique_values(rows, "feeder")),
            "affected_count": first.get("affected_count", ""),
            "affected_peano_count": str(len(affected_peanos)),
            "actual_restoration_minutes": _fmt(actual),
        }
    )
    current_p50 = _to_float(first.get("current_p50"))
    current_q10 = _to_float(first.get("current_q10"))
    current_q90 = _to_float(first.get("current_q90"))
    current_error = abs(current_p50 - actual) if current_p50 is not None else None
    base.update(
        {
            "current_p50": _fmt(current_p50),
            "current_q10": _fmt(current_q10),
            "current_q90": _fmt(current_q90),
            "current_absolute_error": _fmt(current_error),
            "current_covered_q10_q90": _bool_str(_covered(actual, current_q10, current_q90)),
        }
    )
    history = history_by_event.get(first.get("event_id") or "", {})
    history_p50 = _to_float(history.get("history_p50")) if history else None
    history_q10 = _to_float(history.get("history_q10")) if history else None
    history_q90 = _to_float(history.get("history_q90")) if history else None
    if history_p50 is None:
        history_p50 = current_p50
        history_q10 = current_q10
        history_q90 = current_q90
    history_error = abs(history_p50 - actual) if history_p50 is not None else None
    base.update(
        {
            "history_p50": _fmt(history_p50),
            "history_q10": _fmt(history_q10),
            "history_q90": _fmt(history_q90),
            "history_absolute_error": _fmt(history_error),
            "history_covered_q10_q90": _bool_str(_covered(actual, history_q10, history_q90)),
        }
    )
    if first_dt is None:
        base["refresh_notes"] = "missing first Webex event time"
        return base

    eligible = _eligible_refresh_rows(rows, first_dt, actual, post_restore_tolerance_minutes)
    elapsed, refresh_event = max(eligible, key=lambda item: item[0]) if eligible else (0.0, first)
    refresh_p50, refresh_q10, refresh_q90, source, notes = _elapsed_refresh_prediction(
        first_dt,
        elapsed,
        affected_peanos,
        truth_intervals,
        history_p50,
        history_q10,
        history_q90,
        min_history_rows=min_history_rows,
    )
    refresh_error = abs(refresh_p50 - actual) if refresh_p50 is not None else None
    base.update(
        {
            "refresh_event_time": refresh_event.get("event_time", ""),
            "eligible_refresh_event_count": str(len(eligible)),
            "latest_eligible_elapsed_minutes": _fmt(elapsed),
            "refresh_p50": _fmt(refresh_p50),
            "refresh_q10": _fmt(refresh_q10),
            "refresh_q90": _fmt(refresh_q90),
            "refresh_absolute_error": _fmt(refresh_error),
            "refresh_covered_q10_q90": _bool_str(_covered(actual, refresh_q10, refresh_q90)),
            "error_delta_refresh_minus_history": _fmt(_delta(refresh_error, history_error)),
            "refresh_source": source,
            "refresh_notes": _refresh_notes(notes, len(rows), len(eligible), post_restore_tolerance_minutes),
        }
    )
    return base


def _elapsed_refresh_prediction(
    first_dt: datetime,
    elapsed_minutes: float,
    affected_peanos: set[str],
    truth_intervals: list[TruthInterval],
    baseline_p50: float | None,
    baseline_q10: float | None,
    baseline_q90: float | None,
    *,
    min_history_rows: int,
) -> tuple[float | None, float | None, float | None, str, str]:
    prior = [
        interval.actual_restoration_minutes
        for interval in truth_intervals
        if interval.power_restore_time < first_dt and interval.peano in affected_peanos
    ]
    source = "affected_peano_prior"
    if len(prior) < min_history_rows:
        prior = [
            interval.actual_restoration_minutes
            for interval in truth_intervals
            if interval.power_restore_time < first_dt
        ]
        source = "global_prior"
    conditional = [value for value in prior if value >= elapsed_minutes]
    if len(conditional) < min_history_rows:
        conditional = [
            interval.actual_restoration_minutes
            for interval in truth_intervals
            if interval.power_restore_time < first_dt and interval.actual_restoration_minutes >= elapsed_minutes
        ]
        source = "global_conditional_prior"
    if conditional:
        p50 = max(_or_zero(baseline_p50), elapsed_minutes, _quantile(conditional, 0.5))
        q10 = max(elapsed_minutes, _quantile(conditional, 0.1))
        q90 = max(p50, _quantile(conditional, 0.9))
        return p50, q10, q90, source, f"conditional_rows={len(conditional)}"
    p50 = max(_or_zero(baseline_p50), elapsed_minutes)
    q10 = elapsed_minutes
    q90 = max(p50, _or_zero(baseline_q90))
    return p50, q10, q90, "elapsed_floor_only", "no_conditional_prior"


def _eligible_refresh_rows(
    rows: list[dict[str, str]],
    first_dt: datetime,
    actual_minutes: float,
    post_restore_tolerance_minutes: float,
) -> list[tuple[float, dict[str, str]]]:
    eligible = []
    for row in rows:
        event_dt = _parse_dt(row.get("event_time"))
        if event_dt is None:
            continue
        elapsed = (event_dt - first_dt).total_seconds() / 60
        if 0 <= elapsed <= actual_minutes + post_restore_tolerance_minutes:
            eligible.append((elapsed, row))
    return eligible


def _summary(
    rows: list[dict[str, str]],
    min_history_rows: int,
    post_restore_tolerance_minutes: float,
) -> dict[str, Any]:
    current_errors = _numbers(rows, "current_absolute_error")
    history_errors = _numbers(rows, "history_absolute_error")
    refresh_errors = _numbers(rows, "refresh_absolute_error")
    summary = {
        "incidents": len(rows),
        "incidents_with_repeated_webex": sum(1 for row in rows if (_to_float(row.get("event_count")) or 0) > 1),
        "incidents_with_elapsed_refresh": sum(
            1 for row in rows if (_to_float(row.get("latest_eligible_elapsed_minutes")) or 0) > 0
        ),
        "min_history_rows": min_history_rows,
        "post_restore_tolerance_minutes": post_restore_tolerance_minutes,
        "current_q50_mae_minutes": _round_or_none(mean(current_errors) if current_errors else None),
        "current_q10_q90_coverage": _round_or_none(_coverage(rows, "current_covered_q10_q90"), digits=3),
        "history_q50_mae_minutes": _round_or_none(mean(history_errors) if history_errors else None),
        "history_q10_q90_coverage": _round_or_none(_coverage(rows, "history_covered_q10_q90"), digits=3),
        "refresh_q50_mae_minutes": _round_or_none(mean(refresh_errors) if refresh_errors else None),
        "refresh_q10_q90_coverage": _round_or_none(_coverage(rows, "refresh_covered_q10_q90"), digits=3),
        "refresh_source_counts": dict(Counter(row.get("refresh_source") or "<blank>" for row in rows)),
    }
    summary["refresh_gate_status"] = _gate_status(
        summary["refresh_q50_mae_minutes"],
        summary["refresh_q10_q90_coverage"],
    )
    return summary


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    improvements = sorted(
        [row for row in rows if _to_float(row.get("error_delta_refresh_minus_history")) is not None],
        key=lambda row: _to_float(row.get("error_delta_refresh_minus_history")) or 0,
    )[:10]
    residual = sorted(
        [row for row in rows if _to_float(row.get("refresh_absolute_error")) is not None],
        key=lambda row: _to_float(row.get("refresh_absolute_error")) or 0,
        reverse=True,
    )[:10]
    regressions = sorted(
        [row for row in rows if _to_float(row.get("error_delta_refresh_minus_history")) is not None],
        key=lambda row: _to_float(row.get("error_delta_refresh_minus_history")) or 0,
        reverse=True,
    )[:5]
    lines = [
        "# Webex Elapsed Refresh Challenger",
        "",
        "This diagnostic tests a refresh-only ETR update when repeated Webex messages arrive for the same AIS outage incident. It uses only elapsed time from the first Webex message plus time-respecting AIS prior history. It does not expose PEANO lists, raw Webex text, room IDs, tokens, or customer registration names.",
        "",
        "## Summary",
        "",
        f"- Incidents with truth: {summary['incidents']}",
        f"- Incidents with repeated Webex messages: {summary['incidents_with_repeated_webex']}",
        f"- Incidents with positive elapsed refresh signal: {summary['incidents_with_elapsed_refresh']}",
        f"- Current q50 MAE: {_blank(summary['current_q50_mae_minutes'])} min",
        f"- Current q10-q90 coverage: {_blank(summary['current_q10_q90_coverage'])}",
        f"- AIS-history q50 MAE: {_blank(summary['history_q50_mae_minutes'])} min",
        f"- AIS-history q10-q90 coverage: {_blank(summary['history_q10_q90_coverage'])}",
        f"- Webex elapsed refresh q50 MAE: {_blank(summary['refresh_q50_mae_minutes'])} min",
        f"- Webex elapsed refresh q10-q90 coverage: {_blank(summary['refresh_q10_q90_coverage'])}",
        f"- Refresh gate status: {summary['refresh_gate_status']}",
        "",
        "## Refresh Source Mix",
        "",
        "| Source | Incidents |",
        "| --- | ---: |",
    ]
    for source, count in sorted(summary["refresh_source_counts"].items()):
        lines.append(f"| {source} | {count} |")
    lines.extend(
        [
            "",
            "## Biggest Improvements Versus AIS-History Baseline",
            "",
            "| Incident | Webex events | Elapsed | Actual | History p50 | Refresh p50 | Error delta | Source |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in improvements:
        lines.append(
            "| {incident} | {events} | {elapsed} | {actual} | {history} | {refresh} | {delta} | {source} |".format(
                incident=row.get("incident_id", ""),
                events=row.get("event_count", ""),
                elapsed=row.get("latest_eligible_elapsed_minutes", ""),
                actual=row.get("actual_restoration_minutes", ""),
                history=row.get("history_p50", ""),
                refresh=row.get("refresh_p50", ""),
                delta=row.get("error_delta_refresh_minus_history", ""),
                source=row.get("refresh_source", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Biggest Remaining Misses",
            "",
            "| Incident | Webex events | Elapsed | Actual | Refresh p50 | Refresh error | Covered |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in residual:
        lines.append(
            "| {incident} | {events} | {elapsed} | {actual} | {refresh} | {error} | {covered} |".format(
                incident=row.get("incident_id", ""),
                events=row.get("event_count", ""),
                elapsed=row.get("latest_eligible_elapsed_minutes", ""),
                actual=row.get("actual_restoration_minutes", ""),
                refresh=row.get("refresh_p50", ""),
                error=row.get("refresh_absolute_error", ""),
                covered=row.get("refresh_covered_q10_q90", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Largest Regressions",
            "",
            "| Incident | Webex events | Elapsed | Actual | History p50 | Refresh p50 | Error delta |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in regressions:
        lines.append(
            "| {incident} | {events} | {elapsed} | {actual} | {history} | {refresh} | {delta} |".format(
                incident=row.get("incident_id", ""),
                events=row.get("event_count", ""),
                elapsed=row.get("latest_eligible_elapsed_minutes", ""),
                actual=row.get("actual_restoration_minutes", ""),
                history=row.get("history_p50", ""),
                refresh=row.get("refresh_p50", ""),
                delta=row.get("error_delta_refresh_minus_history", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Repeated Webex messages are useful for refresh-time ETR updates, but this is not an initial-send model.",
            "- The diagnostic is truth-bounded: it ignores Webex repeats that occur after the AIS restoration window plus tolerance, so production refresh should use live AIS clear status or another restoration signal before sending updates.",
            "- The MAE remains far above 16 minutes, so the next bottleneck is still missing operational lifecycle/cause/work-type data for long outages.",
        ]
    )
    return "\n".join(lines) + "\n"


def _group_comparison_rows(
    rows: list[dict[str, str]],
    message_by_event: dict[str, str],
    cluster_by_message: dict[str, str],
) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        event_id = row.get("event_id") or ""
        message_id = message_by_event.get(event_id, "")
        cluster_id = cluster_by_message.get(message_id) or event_id
        grouped.setdefault(cluster_id, []).append(row)
    return grouped


def _load_message_by_event(db_path: str | Path) -> dict[str, str]:
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


def _load_cluster_by_message(path: str | Path) -> dict[str, str]:
    output: dict[str, str] = {}
    for row in _read_csv(path):
        message_id = row.get("webex_message_id") or ""
        cluster_id = _extract_truth_cluster_id(row.get("truth_notes") or "")
        if message_id and cluster_id:
            output[message_id] = cluster_id
    return output


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
        for normalized in (_normalize_key(item.get("peano")) for item in payload.get("affected_customers") or [])
        if normalized
    }


def _load_history_baseline(path: str | Path | None) -> dict[str, dict[str, str]]:
    if not path or not Path(path).exists():
        return {}
    return {row.get("event_id", ""): row for row in _read_csv(path) if row.get("event_id")}


def _load_truth_intervals(path: str | Path) -> list[TruthInterval]:
    intervals: list[TruthInterval] = []
    for row in _read_csv(path):
        if str(row.get("truth_quality") or "").strip().upper() != "OK":
            continue
        peano = _normalize_key(row.get("peano"))
        start = _parse_dt(row.get("outage_start_time"))
        restore = _parse_dt(row.get("power_restore_time"))
        actual = _to_float(row.get("actual_restoration_minutes"))
        if not peano or start is None or restore is None or actual is None or actual <= 5 or actual > 1440:
            continue
        intervals.append(
            TruthInterval(
                peano=peano,
                outage_start_time=start,
                power_restore_time=restore,
                actual_restoration_minutes=actual,
            )
        )
    return sorted(intervals, key=lambda item: item.outage_start_time)


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


def _extract_truth_cluster_id(notes: str) -> str:
    match = re.search(r"(?:^|;\s*)truth_cluster_id=([^;]+)", notes or "")
    return match.group(1).strip() if match else ""


def _cluster_sort_key(rows: list[dict[str, str]]) -> tuple[datetime, str]:
    first = min((_parse_dt(row.get("event_time")) or datetime.max for row in rows), default=datetime.max)
    return first, rows[0].get("event_id") or ""


def _refresh_notes(notes: str, event_count: int, eligible_count: int, tolerance: float) -> str:
    parts = [notes]
    if event_count > 1 and eligible_count <= 1:
        parts.append("no_repeated_webex_before_truth_restore_window")
    parts.append(f"post_restore_tolerance_minutes={_fmt(tolerance)}")
    return "; ".join(part for part in parts if part)


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


def _covered(actual: float, q10: float | None, q90: float | None) -> bool | None:
    if q10 is None or q90 is None:
        return None
    return q10 <= actual <= q90


def _unique_values(rows: list[dict[str, str]], column: str) -> list[str]:
    return sorted({str(row.get(column) or "").strip() for row in rows if str(row.get(column) or "").strip()})


def _join_limited(values: list[str], limit: int = 3) -> str:
    if len(values) <= limit:
        return "|".join(values)
    return "|".join(values[:limit]) + f"|+{len(values) - limit}"


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
