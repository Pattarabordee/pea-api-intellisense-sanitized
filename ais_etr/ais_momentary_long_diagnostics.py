from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any


DIAGNOSTIC_COLUMNS = (
    "event_id",
    "webex_message_ref",
    "event_time",
    "district",
    "device_id",
    "feeder",
    "webex_open_close_minutes",
    "event_age_band",
    "ais_elapsed_since_start_minutes",
    "ais_remaining_minutes",
    "current_p50",
    "current_absolute_error",
    "current_covered_q10_q90",
    "ais_matched_site_count",
    "ais_matched_rows",
    "repeat_cluster_id",
    "repeat_cluster_size",
    "prior_same_device_gap_minutes",
    "mismatch_pattern",
    "mismatch_flags",
    "review_priority",
    "recommended_action",
)

SEGMENT_COLUMNS = (
    "dimension",
    "segment",
    "rows",
    "high_error_rows",
    "mean_absolute_error_minutes",
    "mean_remaining_minutes",
    "coverage",
)


def build_ais_momentary_long_diagnostics(
    triage_csv: str | Path,
    readiness_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    segments_output: str | Path | None = None,
    *,
    cluster_gap_minutes: float = 180.0,
    late_webex_minutes: float = 30.0,
    high_error_minutes: float = 60.0,
) -> dict[str, Any]:
    readiness_by_event = {row.get("event_id", ""): row for row in _read_csv(readiness_csv)}
    target_rows = [
        row
        for row in _read_csv(triage_csv)
        if row.get("primary_root_cause") == "webex_momentary_long_ais_interval"
        or "webex_momentary_but_ais_sustained" in (row.get("root_cause_flags") or "")
    ]
    cluster_info = _cluster_rows(target_rows, cluster_gap_minutes)
    rows = [
        _diagnostic_row(
            row,
            readiness_by_event.get(row.get("event_id") or "", {}),
            cluster_info.get(row.get("event_id") or "", {}),
            late_webex_minutes=late_webex_minutes,
            high_error_minutes=high_error_minutes,
        )
        for row in target_rows
    ]
    _write_csv(output_csv, DIAGNOSTIC_COLUMNS, rows)
    segments = _build_segments(rows, high_error_minutes)
    if segments_output:
        _write_csv(segments_output, SEGMENT_COLUMNS, segments)
    summary = _summarize(rows, segments, high_error_minutes, late_webex_minutes, cluster_gap_minutes)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, rows, segments), encoding="utf-8-sig")
    return {
        **summary,
        "triage_csv": str(triage_csv),
        "readiness_csv": str(readiness_csv),
        "output_csv": str(output_csv),
        "segments_output": str(segments_output) if segments_output else None,
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def _diagnostic_row(
    triage: dict[str, str],
    readiness: dict[str, str],
    cluster: dict[str, Any],
    *,
    late_webex_minutes: float,
    high_error_minutes: float,
) -> dict[str, str]:
    elapsed = _to_float(triage.get("ais_elapsed_since_start_minutes"))
    remaining = _to_float(triage.get("ais_remaining_minutes"))
    p50 = _to_float(triage.get("current_p50"))
    error = _to_float(triage.get("current_absolute_error")) or 0.0
    open_close = _to_float(readiness.get("webex_open_close_minutes"))
    cluster_size = int(cluster.get("cluster_size") or 1)
    prior_gap = cluster.get("prior_gap_minutes")
    flags = _flags(
        elapsed=elapsed,
        remaining=remaining,
        p50=p50,
        error=error,
        open_close=open_close,
        cluster_size=cluster_size,
        late_webex_minutes=late_webex_minutes,
        high_error_minutes=high_error_minutes,
    )
    pattern = _pattern(flags)
    return {
        "event_id": triage.get("event_id", ""),
        "webex_message_ref": triage.get("webex_message_ref", ""),
        "event_time": triage.get("event_time", ""),
        "district": triage.get("district", ""),
        "device_id": triage.get("device_id", ""),
        "feeder": triage.get("feeder", ""),
        "webex_open_close_minutes": readiness.get("webex_open_close_minutes", ""),
        "event_age_band": triage.get("event_age_band", ""),
        "ais_elapsed_since_start_minutes": triage.get("ais_elapsed_since_start_minutes", ""),
        "ais_remaining_minutes": triage.get("ais_remaining_minutes", ""),
        "current_p50": triage.get("current_p50", ""),
        "current_absolute_error": triage.get("current_absolute_error", ""),
        "current_covered_q10_q90": triage.get("current_covered_q10_q90", ""),
        "ais_matched_site_count": triage.get("ais_matched_site_count", ""),
        "ais_matched_rows": triage.get("ais_matched_rows", ""),
        "repeat_cluster_id": str(cluster.get("cluster_id") or ""),
        "repeat_cluster_size": str(cluster_size),
        "prior_same_device_gap_minutes": _fmt(prior_gap),
        "mismatch_pattern": pattern,
        "mismatch_flags": ";".join(flags),
        "review_priority": _priority(pattern, error, remaining, high_error_minutes),
        "recommended_action": _recommended_action(pattern),
    }


def _flags(
    *,
    elapsed: float | None,
    remaining: float | None,
    p50: float | None,
    error: float,
    open_close: float | None,
    cluster_size: int,
    late_webex_minutes: float,
    high_error_minutes: float,
) -> list[str]:
    flags = []
    if open_close is not None and open_close <= 1.0:
        flags.append("webex_reclosed_under_1m")
    if remaining is not None and remaining > 5.0:
        flags.append("ais_sustained_after_webex_momentary")
    if cluster_size >= 2:
        flags.append("repeat_same_device_cluster")
    if elapsed is not None and elapsed >= late_webex_minutes:
        flags.append("late_in_active_ais_interval")
    if elapsed is not None and elapsed <= 5.0:
        flags.append("near_ais_outage_start")
    if remaining is not None and remaining >= 120.0:
        flags.append("long_remaining_ais_outage")
    if remaining is not None and p50 is not None and error >= high_error_minutes and p50 < remaining * 0.5:
        flags.append("model_ignores_active_ais_remaining_state")
    if error >= high_error_minutes:
        flags.append("high_error")
    return _dedupe(flags) or ["needs_review"]


def _pattern(flags: list[str]) -> str:
    flag_set = set(flags)
    if "repeat_same_device_cluster" in flag_set and "late_in_active_ais_interval" in flag_set:
        return "repeat_operation_during_active_ais_outage"
    if "repeat_same_device_cluster" in flag_set:
        return "repeat_momentary_cluster_needs_incident_grouping"
    if "late_in_active_ais_interval" in flag_set:
        return "late_observation_during_active_ais_outage"
    if "near_ais_outage_start" in flag_set and "long_remaining_ais_outage" in flag_set:
        return "early_momentary_signal_of_long_ais_outage"
    if "model_ignores_active_ais_remaining_state" in flag_set:
        return "model_feature_gap_active_ais_state"
    return "single_momentary_active_ais_review"


def _priority(pattern: str, error: float, remaining: float | None, high_error_minutes: float) -> str:
    if error >= 120 or (remaining is not None and remaining >= 180):
        return "P1"
    if pattern == "repeat_operation_during_active_ais_outage" and error >= high_error_minutes:
        return "P1"
    if pattern in {
        "repeat_operation_during_active_ais_outage",
        "early_momentary_signal_of_long_ais_outage",
        "model_feature_gap_active_ais_state",
    }:
        return "P2"
    return "P3"


def _recommended_action(pattern: str) -> str:
    return {
        "repeat_operation_during_active_ais_outage": "Group repeated Webex operations into one AIS active-outage incident before model evaluation.",
        "repeat_momentary_cluster_needs_incident_grouping": "Add device/feeder incident clustering before treating each Webex row as an independent event.",
        "late_observation_during_active_ais_outage": "Add elapsed-since-AIS-outage-start and active AIS state to notification-time prediction.",
        "early_momentary_signal_of_long_ais_outage": "Use live AIS active alarm state to override momentary Webex-only interpretation.",
        "model_feature_gap_active_ais_state": "Build an AIS-state challenger feature set before tuning baseline quantiles.",
        "single_momentary_active_ais_review": "Keep in review queue and compare with AIS alarm interval details.",
    }.get(pattern, "Review before model tuning.")


def _cluster_rows(rows: list[dict[str, str]], cluster_gap_minutes: float) -> dict[str, dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row.get("feeder", ""), row.get("device_id", ""))].append({**row, "_dt": _parse_dt(row.get("event_time"))})
    output: dict[str, dict[str, Any]] = {}
    for (feeder, device), values in grouped.items():
        values = sorted(values, key=lambda row: row.get("_dt") or datetime.min)
        cluster_index = 0
        current: list[dict[str, Any]] = []
        previous_dt: datetime | None = None
        previous_event_id = ""
        for row in values:
            dt = row.get("_dt")
            gap = None if previous_dt is None or dt is None else (dt - previous_dt).total_seconds() / 60.0
            if not current or gap is None or gap > cluster_gap_minutes:
                _flush_cluster(output, current, feeder, device, cluster_index)
                cluster_index += 1
                current = []
            row["_prior_gap"] = gap
            row["_previous_event_id"] = previous_event_id
            current.append(row)
            previous_dt = dt
            previous_event_id = row.get("event_id", "")
        _flush_cluster(output, current, feeder, device, cluster_index)
    return output


def _flush_cluster(
    output: dict[str, dict[str, Any]],
    cluster: list[dict[str, Any]],
    feeder: str,
    device: str,
    cluster_index: int,
) -> None:
    if not cluster:
        return
    cluster_id = f"{feeder or 'unknown'}|{device or 'unknown'}|{cluster_index}"
    for row in cluster:
        output[row.get("event_id", "")] = {
            "cluster_id": cluster_id,
            "cluster_size": len(cluster),
            "prior_gap_minutes": row.get("_prior_gap"),
        }


def _build_segments(rows: list[dict[str, str]], high_error_minutes: float) -> list[dict[str, str]]:
    output = []
    for dimension in ("mismatch_pattern", "feeder", "device_id", "event_age_band", "review_priority"):
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            grouped[row.get(dimension) or "<blank>"].append(row)
        for segment, values in grouped.items():
            output.append(_segment_row(dimension, segment, values, high_error_minutes))
    return sorted(
        output,
        key=lambda row: (
            0 if row["dimension"] == "mismatch_pattern" else 1,
            -_to_int(row["high_error_rows"]),
            -_to_int(row["rows"]),
            row["dimension"],
            row["segment"],
        ),
    )


def _segment_row(dimension: str, segment: str, rows: list[dict[str, str]], high_error_minutes: float) -> dict[str, str]:
    return {
        "dimension": dimension,
        "segment": segment,
        "rows": str(len(rows)),
        "high_error_rows": str(sum(1 for row in rows if (_to_float(row.get("current_absolute_error")) or 0) >= high_error_minutes)),
        "mean_absolute_error_minutes": _fmt(_mean(_numbers(rows, "current_absolute_error"))),
        "mean_remaining_minutes": _fmt(_mean(_numbers(rows, "ais_remaining_minutes"))),
        "coverage": _fmt(_coverage(rows), digits=3),
    }


def _summarize(
    rows: list[dict[str, str]],
    segments: list[dict[str, str]],
    high_error_minutes: float,
    late_webex_minutes: float,
    cluster_gap_minutes: float,
) -> dict[str, Any]:
    pattern_counts = Counter(row.get("mismatch_pattern") or "<blank>" for row in rows)
    priority_counts = Counter(row.get("review_priority") or "<blank>" for row in rows)
    high_error_rows = [row for row in rows if (_to_float(row.get("current_absolute_error")) or 0) >= high_error_minutes]
    repeat_rows = [row for row in rows if _to_int(row.get("repeat_cluster_size")) >= 2]
    return {
        "momentary_long_rows": len(rows),
        "high_error_rows": len(high_error_rows),
        "repeat_cluster_rows": len(repeat_rows),
        "unique_repeat_clusters": len({row["repeat_cluster_id"] for row in repeat_rows if row.get("repeat_cluster_id")}),
        "pattern_counts": dict(pattern_counts.most_common()),
        "priority_counts": dict(priority_counts.most_common()),
        "mae": _fmt(_mean(_numbers(rows, "current_absolute_error"))),
        "coverage": _fmt(_coverage(rows), digits=3),
        "high_error_minutes": high_error_minutes,
        "late_webex_minutes": late_webex_minutes,
        "cluster_gap_minutes": cluster_gap_minutes,
        "recommendation": _summary_recommendation(pattern_counts),
    }


def _summary_recommendation(pattern_counts: Counter[str]) -> str:
    if not pattern_counts:
        return "No momentary-long AIS mismatch rows were found."
    top = pattern_counts.most_common(1)[0][0]
    if top in {"repeat_operation_during_active_ais_outage", "repeat_momentary_cluster_needs_incident_grouping"}:
        return "Prioritize Webex incident clustering before model tuning; repeated momentary rows should not be independent training events."
    if top == "late_observation_during_active_ais_outage":
        return "Prioritize active AIS elapsed-time features for notification-time prediction."
    if top == "early_momentary_signal_of_long_ais_outage":
        return "Prioritize live AIS active-alarm state as an override to momentary Webex interpretation."
    return "Keep this group in review and add AIS active-state features before tuning."


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]], segments: list[dict[str, str]]) -> str:
    pattern_segments = [row for row in segments if row.get("dimension") == "mismatch_pattern"]
    top_rows = sorted(rows, key=lambda row: -(_to_float(row.get("current_absolute_error")) or 0))[:15]
    lines = [
        "# AIS Momentary-Long Mismatch Diagnostic",
        "",
        "This report focuses on Webex rows that look momentary while AIS truth shows a sustained active outage. It is shadow-only and does not change customer notification behavior.",
        "",
        "## Summary",
        "",
        f"- Momentary-long rows: {summary['momentary_long_rows']}",
        f"- High-error rows: {summary['high_error_rows']}",
        f"- Rows in repeat clusters: {summary['repeat_cluster_rows']}",
        f"- Unique repeat clusters: {summary['unique_repeat_clusters']}",
        f"- MAE: {summary['mae']}",
        f"- q10-q90 coverage: {summary['coverage']}",
        "",
        "## Mismatch Patterns",
        "",
        "| Pattern | Rows | High-error | MAE | Remaining | Coverage |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in pattern_segments:
        lines.append(
            "| {segment} | {rows} | {high} | {mae} | {remaining} | {coverage} |".format(
                segment=row["segment"],
                rows=row["rows"],
                high=row["high_error_rows"],
                mae=row["mean_absolute_error_minutes"],
                remaining=row["mean_remaining_minutes"],
                coverage=row["coverage"],
            )
        )
    lines.extend(["", "## Review Priority", "", "| Priority | Rows |", "| --- | ---: |"])
    for priority, count in summary["priority_counts"].items():
        lines.append(f"| {priority} | {count} |")
    lines.extend(
        [
            "",
            "## Top Rows",
            "",
            "| Event ref | Time | Device | Feeder | AIS remaining | p50 | Error | Pattern | Priority |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in top_rows:
        lines.append(
            "| {ref} | {time} | {device} | {feeder} | {remaining} | {p50} | {error} | {pattern} | {priority} |".format(
                ref=row.get("webex_message_ref", ""),
                time=row.get("event_time", ""),
                device=row.get("device_id", ""),
                feeder=row.get("feeder", ""),
                remaining=row.get("ais_remaining_minutes", ""),
                p50=row.get("current_p50", ""),
                error=row.get("current_absolute_error", ""),
                pattern=row.get("mismatch_pattern", ""),
                priority=row.get("review_priority", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            str(summary["recommendation"]),
            "",
            "Do not tune/promote the model from this group until Webex rows are grouped by incident and live AIS active-state features are available.",
            "",
            "## Safety Notes",
            "",
            "- Outputs use redacted event references, device, feeder, and aggregate AIS counts only.",
            "- Outputs omit source chat bodies, space identifiers, credential values, meter-id lists, and unnecessary customer identity fields.",
        ]
    )
    return "\n".join(lines) + "\n"


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


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("T", " ").replace("Z", "")
    if not text:
        return None
    if "+" in text:
        text = text.split("+", 1)[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _numbers(rows: list[dict[str, str]], column: str) -> list[float]:
    return [value for row in rows if (value := _to_float(row.get(column))) is not None]


def _mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _coverage(rows: list[dict[str, str]]) -> float | None:
    values = [str(row.get("current_covered_q10_q90") or "").strip().upper() for row in rows]
    values = [value for value in values if value in {"TRUE", "FALSE"}]
    if not values:
        return None
    return sum(1 for value in values if value == "TRUE") / len(values)


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


def _fmt(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")


def _dedupe(values: list[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output
