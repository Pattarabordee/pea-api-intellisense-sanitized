from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


LIFECYCLE_TEMPLATE_COLUMNS = (
    "event_id",
    "incident_id",
    "event_time",
    "device_id",
    "feeder",
    "actual_restoration_minutes",
    "current_p50",
    "current_absolute_error",
    "long_outage_refresh_p50",
    "long_outage_refresh_error",
    "webex_elapsed_refresh_p50",
    "webex_elapsed_refresh_error",
    "priority_rank",
    "event_number",
    "source_system",
    "outage_reported_time",
    "crew_dispatched_time",
    "crew_arrived_time",
    "fault_located_time",
    "switching_completed_time",
    "first_restore_time",
    "event_closed_time",
    "cause_group",
    "cause_code",
    "work_type",
    "job_status_at_notification",
    "job_status_at_30m",
    "job_status_at_60m",
    "crew_count",
    "material_required",
    "weather_impact",
    "reviewed_by",
    "review_notes",
)

REQUIRED_VALIDATION_COLUMNS = (
    "event_id",
    "event_time",
    "source_system",
    "outage_reported_time",
    "first_restore_time",
)

TIMESTAMP_COLUMNS = (
    "event_time",
    "outage_reported_time",
    "crew_dispatched_time",
    "crew_arrived_time",
    "fault_located_time",
    "switching_completed_time",
    "first_restore_time",
    "event_closed_time",
)


def build_ops_lifecycle_template(
    comparison_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    long_outage_csv: str | Path | None = None,
    webex_elapsed_csv: str | Path | None = None,
    horizon_minutes: int = 60,
    top_n: int = 50,
) -> dict[str, Any]:
    comparison_rows = _read_csv(comparison_csv)
    long_refresh_by_event = _load_long_refresh_by_event(long_outage_csv, horizon_minutes)
    webex_refresh_by_event = _load_webex_refresh_by_event(webex_elapsed_csv)
    candidates = []
    for row in comparison_rows:
        actual = _to_float(row.get("actual_restoration_minutes"))
        if actual is None:
            continue
        event_id = row.get("event_id") or ""
        long_refresh = long_refresh_by_event.get(event_id, {})
        webex_refresh = webex_refresh_by_event.get(event_id, {})
        webex_error = _to_float(webex_refresh.get("refresh_absolute_error"))
        long_error = _to_float(long_refresh.get("refresh_absolute_error"))
        current_error = _to_float(row.get("current_absolute_error"))
        priority_error = webex_error if webex_error is not None else (long_error if long_error is not None else current_error)
        if priority_error is None:
            continue
        candidates.append((priority_error, row, long_refresh, webex_refresh))

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = candidates[: max(top_n, 0)]
    output_rows = []
    for rank, (_error, row, long_refresh, webex_refresh) in enumerate(selected, start=1):
        output_rows.append(_template_row(row, long_refresh, webex_refresh, rank))
    _write_csv(output_csv, LIFECYCLE_TEMPLATE_COLUMNS, output_rows)
    summary = {
        "comparison_csv": str(comparison_csv),
        "long_outage_csv": str(long_outage_csv) if long_outage_csv else None,
        "webex_elapsed_csv": str(webex_elapsed_csv) if webex_elapsed_csv else None,
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "horizon_minutes": horizon_minutes,
        "candidate_incidents": len(candidates),
        "template_rows": len(output_rows),
        "top_error_minutes": _round_or_none(selected[0][0] if selected else None),
        "median_priority_error_minutes": _round_or_none(_median([item[0] for item in selected])),
    }
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_template_markdown(summary, output_rows), encoding="utf-8-sig")
    return summary


def validate_ops_lifecycle_file(
    input_csv: str | Path,
    output_valid_csv: str | Path | None = None,
    rejects_csv: str | Path | None = None,
    markdown_output: str | Path | None = None,
) -> dict[str, Any]:
    rows = _read_csv(input_csv)
    valid_rows = []
    reject_rows = []
    issue_counts: Counter[str] = Counter()
    for index, row in enumerate(rows, start=2):
        issues = _validation_issues(row)
        if issues:
            issue_counts.update(issues)
            reject_rows.append({**row, "source_row_number": str(index), "validation_issues": ";".join(issues)})
        else:
            valid_rows.append(row)
    if output_valid_csv:
        columns = _merged_columns(rows, extra=())
        _write_csv(output_valid_csv, columns, valid_rows)
    if rejects_csv:
        columns = _merged_columns(rows, extra=("source_row_number", "validation_issues"))
        _write_csv(rejects_csv, columns, reject_rows)
    summary = {
        "input_csv": str(input_csv),
        "output_valid_csv": str(output_valid_csv) if output_valid_csv else None,
        "rejects_csv": str(rejects_csv) if rejects_csv else None,
        "markdown_output": str(markdown_output) if markdown_output else None,
        "rows": len(rows),
        "valid_rows": len(valid_rows),
        "reject_rows": len(reject_rows),
        "issue_counts": dict(sorted(issue_counts.items())),
    }
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_validation_markdown(summary), encoding="utf-8-sig")
    return summary


def _template_row(row: dict[str, str], long_refresh: dict[str, str], webex_refresh: dict[str, str], rank: int) -> dict[str, str]:
    return {
        **{column: "" for column in LIFECYCLE_TEMPLATE_COLUMNS},
        "event_id": row.get("event_id", ""),
        "incident_id": row.get("incident_id", ""),
        "event_time": row.get("event_time", ""),
        "device_id": row.get("device_id", ""),
        "feeder": row.get("feeder", ""),
        "actual_restoration_minutes": row.get("actual_restoration_minutes", ""),
        "current_p50": row.get("current_p50", ""),
        "current_absolute_error": row.get("current_absolute_error", ""),
        "long_outage_refresh_p50": long_refresh.get("refresh_p50", ""),
        "long_outage_refresh_error": long_refresh.get("refresh_absolute_error", ""),
        "webex_elapsed_refresh_p50": webex_refresh.get("refresh_p50", ""),
        "webex_elapsed_refresh_error": webex_refresh.get("refresh_absolute_error", ""),
        "priority_rank": str(rank),
        "source_system": "eRespond",
    }


def _load_long_refresh_by_event(path: str | Path | None, horizon_minutes: int) -> dict[str, dict[str, str]]:
    if not path or not Path(path).exists():
        return {}
    rows = _read_csv(path)
    return {
        row.get("event_id", ""): row
        for row in rows
        if row.get("event_id") and str(row.get("horizon_minutes") or "") == str(horizon_minutes)
    }


def _load_webex_refresh_by_event(path: str | Path | None) -> dict[str, dict[str, str]]:
    if not path or not Path(path).exists():
        return {}
    rows = _read_csv(path)
    return {row.get("event_id", ""): row for row in rows if row.get("event_id")}


def _validation_issues(row: dict[str, str]) -> list[str]:
    issues = []
    for column in REQUIRED_VALIDATION_COLUMNS:
        if not str(row.get(column) or "").strip():
            issues.append(f"missing_{column}")
    parsed_times = {column: _parse_dt(row.get(column)) for column in TIMESTAMP_COLUMNS if str(row.get(column) or "").strip()}
    for column, value in parsed_times.items():
        if value is None:
            issues.append(f"invalid_{column}")
    event_time = parsed_times.get("event_time")
    first_restore = parsed_times.get("first_restore_time")
    outage_reported = parsed_times.get("outage_reported_time")
    if event_time and first_restore and first_restore < event_time:
        issues.append("first_restore_before_event_time")
    if outage_reported and first_restore and first_restore < outage_reported:
        issues.append("first_restore_before_outage_reported")
    sequence = [
        "outage_reported_time",
        "crew_dispatched_time",
        "crew_arrived_time",
        "fault_located_time",
        "switching_completed_time",
        "first_restore_time",
        "event_closed_time",
    ]
    previous_column = ""
    previous_value: datetime | None = None
    for column in sequence:
        value = parsed_times.get(column)
        if value is None:
            continue
        if previous_value and value < previous_value:
            issues.append(f"{column}_before_{previous_column}")
        previous_value = value
        previous_column = column
    return issues


def _render_template_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    lines = [
        "# Operational Lifecycle Intake Template",
        "",
        "This template targets the incidents that still dominate AIS ETR error after AIS-history, Webex elapsed refresh, and long-outage refresh diagnostics. It avoids PEANO lists, raw Webex text, room IDs, tokens, and customer registration names.",
        "",
        "## Summary",
        "",
        f"- Candidate incidents with truth: {summary['candidate_incidents']}",
        f"- Template rows created: {summary['template_rows']}",
        f"- Long-outage horizon available: {summary['horizon_minutes']} minutes",
        "- Priority error source order: Webex elapsed refresh, long-outage refresh, then current model.",
        f"- Highest remaining error: {_blank(summary['top_error_minutes'])} minutes",
        f"- Median selected priority error: {_blank(summary['median_priority_error_minutes'])} minutes",
        "",
        "## Fields To Fill",
        "",
        "- Required for validation: `source_system`, `outage_reported_time`, `first_restore_time`.",
        "- High-value model fields: `cause_group`, `cause_code`, `work_type`, `crew_dispatched_time`, `crew_arrived_time`, `fault_located_time`, `switching_completed_time`, `job_status_at_notification`, `job_status_at_30m`, `job_status_at_60m`.",
        "- The model gate should use timestamps and statuses that are available as-of the prediction or refresh time only.",
        "",
        "## Top Priority Incidents",
        "",
        "| Rank | Incident | Event time | Feeder | Actual | Current error | Long refresh error | Webex elapsed error |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows[:10]:
        lines.append(
            f"| {row.get('priority_rank')} | {row.get('incident_id')} | {row.get('event_time')} | "
            f"{row.get('feeder')} | {row.get('actual_restoration_minutes')} | "
            f"{row.get('current_absolute_error')} | {row.get('long_outage_refresh_error')} | "
            f"{row.get('webex_elapsed_refresh_error')} |"
        )
    lines.extend(
        [
            "",
            "## Output",
            "",
            f"- Template CSV: `{summary['output_csv']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_validation_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Operational Lifecycle Validation",
        "",
        "This validation checks whether the lifecycle intake file is ready for as-of feature engineering and shadow evaluation.",
        "",
        "## Summary",
        "",
        f"- Rows: {summary['rows']}",
        f"- Valid rows: {summary['valid_rows']}",
        f"- Reject rows: {summary['reject_rows']}",
        "",
        "## Issue Counts",
        "",
        "| Issue | Rows |",
        "| --- | ---: |",
    ]
    for issue, count in summary["issue_counts"].items():
        lines.append(f"| {issue} | {count} |")
    if not summary["issue_counts"]:
        lines.append("| none | 0 |")
    return "\n".join(lines) + "\n"


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: str | Path, columns: tuple[str, ...] | list[str], rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _merged_columns(rows: list[dict[str, str]], *, extra: tuple[str, ...]) -> list[str]:
    columns = list(rows[0].keys()) if rows else list(LIFECYCLE_TEMPLATE_COLUMNS)
    for column in extra:
        if column not in columns:
            columns.append(column)
    return columns


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("T", " ").removesuffix("Z")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


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


def _blank(value: Any) -> str:
    return "" if value is None else str(value)
