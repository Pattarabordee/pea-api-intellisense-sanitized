from __future__ import annotations

import csv
from collections import Counter
import json
from pathlib import Path
import sqlite3
from statistics import mean
from typing import Any

from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN, GATE_Q50_MAE_MAX


DEVICE_STATE_COLUMNS = (
    "event_id",
    "webex_message_ref",
    "event_time",
    "device_type",
    "device_id",
    "feeder",
    "webex_device_interruption_class",
    "webex_open_close_minutes",
    "actual_restoration_minutes",
    "current_p50",
    "current_absolute_error",
    "current_covered_q10_q90",
    "review_action",
)


def build_webex_device_state_diagnostic(
    db_path: str | Path,
    comparison_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
) -> dict[str, Any]:
    comparison_rows = [
        row
        for row in _read_csv(comparison_csv)
        if _to_float(row.get("actual_restoration_minutes")) is not None
    ]
    parsed_by_event = _load_parsed_fields_by_event(db_path)
    rows = [_build_row(row, parsed_by_event.get(row.get("event_id") or "", {})) for row in comparison_rows]
    _write_csv(output_csv, DEVICE_STATE_COLUMNS, rows)
    summary = _summary(rows)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, rows), encoding="utf-8-sig")
    return {
        **summary,
        "db_path": str(db_path),
        "comparison_csv": str(comparison_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def _build_row(row: dict[str, str], parsed_fields: dict[str, Any]) -> dict[str, str]:
    device_class = str(parsed_fields.get("webex_device_interruption_class") or "unknown")
    return {
        "event_id": row.get("event_id", ""),
        "webex_message_ref": row.get("webex_message_ref", ""),
        "event_time": row.get("event_time", ""),
        "device_type": row.get("device_type", ""),
        "device_id": row.get("device_id", ""),
        "feeder": row.get("feeder", ""),
        "webex_device_interruption_class": device_class,
        "webex_open_close_minutes": _fmt(_to_float(parsed_fields.get("webex_open_close_minutes"))),
        "actual_restoration_minutes": row.get("actual_restoration_minutes", ""),
        "current_p50": row.get("current_p50", ""),
        "current_absolute_error": row.get("current_absolute_error", ""),
        "current_covered_q10_q90": row.get("current_covered_q10_q90", ""),
        "review_action": _review_action(device_class),
    }


def _summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    by_class = []
    for device_class in sorted({row.get("webex_device_interruption_class") or "unknown" for row in rows}):
        group = [row for row in rows if (row.get("webex_device_interruption_class") or "unknown") == device_class]
        by_class.append(
            {
                "webex_device_interruption_class": device_class,
                "rows": len(group),
                "mean_actual_minutes": _round_or_none(_mean(_numbers(group, "actual_restoration_minutes"))),
                "current_q50_mae_minutes": _round_or_none(_mean(_numbers(group, "current_absolute_error"))),
                "current_q10_q90_coverage": _round_or_none(_coverage(group), digits=3),
                "share_of_total_error": _round_or_none(_error_share(group, rows), digits=3),
            }
        )
    sustained_like = [
        row
        for row in rows
        if row.get("webex_device_interruption_class") in {"sustained_candidate", "open_gt_5m", "trip_no_open_close"}
    ]
    sustained_metrics = _metrics(sustained_like)
    return {
        "with_truth": len(rows),
        "class_counts": dict(Counter(row.get("webex_device_interruption_class") or "unknown" for row in rows)),
        "by_class": by_class,
        "sustained_like_metrics": sustained_metrics,
        "sustained_like_gate_status": _gate_status(sustained_metrics),
    }


def _metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "current_q50_mae_minutes": _round_or_none(_mean(_numbers(rows, "current_absolute_error"))),
        "current_q10_q90_coverage": _round_or_none(_coverage(rows), digits=3),
    }


def _render_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    top_errors = sorted(
        rows,
        key=lambda row: _to_float(row.get("current_absolute_error")) or -1,
        reverse=True,
    )[:10]
    sustained = summary["sustained_like_metrics"]
    lines = [
        "# Webex Device-State Error Diagnostic",
        "",
        "This diagnostic separates Webex device operations that reclosed quickly from sustained candidates before interpreting AIS ETR model error. It does not expose raw Webex text, room IDs, tokens, PEANO lists, or customer registration names.",
        "",
        "## Summary",
        "",
        f"- Rows with AIS truth: {summary['with_truth']}",
        f"- Sustained-like rows: {sustained['rows']}",
        f"- Sustained-like current MAE: {_blank(sustained['current_q50_mae_minutes'])} min",
        f"- Sustained-like q10-q90 coverage: {_blank(sustained['current_q10_q90_coverage'])}",
        f"- Sustained-like gate status: {summary['sustained_like_gate_status']}",
        "",
        "## Error By Webex Device State",
        "",
        "| Device state | Rows | Mean actual | Current MAE | Coverage | Error share |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in summary["by_class"]:
        lines.append(
            "| {klass} | {rows} | {actual} | {mae} | {coverage} | {share} |".format(
                klass=item["webex_device_interruption_class"],
                rows=item["rows"],
                actual=_blank(item["mean_actual_minutes"]),
                mae=_blank(item["current_q50_mae_minutes"]),
                coverage=_blank(item["current_q10_q90_coverage"]),
                share=_blank(item["share_of_total_error"]),
            )
        )
    lines.extend(
        [
            "",
            "## Top Error Rows",
            "",
            "| Event ref | Event time | Device | Feeder | Device state | Actual | Current p50 | Error |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: |",
        ]
    )
    for row in top_errors:
        lines.append(
            "| {ref} | {time} | {device} | {feeder} | {state} | {actual} | {p50} | {error} |".format(
                ref=row.get("webex_message_ref", ""),
                time=row.get("event_time", ""),
                device=row.get("device_id") or row.get("device_type") or "",
                feeder=row.get("feeder", ""),
                state=row.get("webex_device_interruption_class", ""),
                actual=row.get("actual_restoration_minutes", ""),
                p50=row.get("current_p50", ""),
                error=row.get("current_absolute_error", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Momentary Webex operations should be a review or low-confidence class for customer-facing ETR until a downstream AIS/site outage is confirmed.",
            "- Sustained-like Webex candidates still fail the q50 MAE gate, so device state is necessary triage but not sufficient for the final model.",
            "- The next model feature lane should combine device-state classification with live AIS active-alarm state and eRespond/field-work lifecycle fields.",
        ]
    )
    return "\n".join(lines) + "\n"


def _load_parsed_fields_by_event(db_path: str | Path) -> dict[str, dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return {}
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        output: dict[str, dict[str, Any]] = {}
        for event_id, parsed_json in conn.execute("SELECT event_id, parsed_json FROM outage_events").fetchall():
            try:
                parsed = json.loads(parsed_json or "{}")
            except Exception:
                parsed = {}
            fields = parsed.get("parsed_fields") or {}
            output[str(event_id)] = fields if isinstance(fields, dict) else {}
        return output
    finally:
        conn.close()


def _review_action(device_class: str) -> str:
    if device_class in {"momentary_le_1m", "short_le_5m"}:
        return "review_before_customer_etr"
    if device_class in {"sustained_candidate", "open_gt_5m", "trip_no_open_close"}:
        return "eligible_for_sustained_shadow_evaluation"
    return "needs_parser_or_source_review"


def _gate_status(metrics: dict[str, Any]) -> str:
    mae = metrics.get("current_q50_mae_minutes")
    coverage = metrics.get("current_q10_q90_coverage")
    if mae is None or coverage is None:
        return "missing_metric"
    if float(mae) <= GATE_Q50_MAE_MAX and GATE_COVERAGE_MIN <= float(coverage) <= GATE_COVERAGE_MAX:
        return "gate_pass"
    return "gate_fail"


def _numbers(rows: list[dict[str, str]], column: str) -> list[float]:
    return [value for value in (_to_float(row.get(column)) for row in rows) if value is not None]


def _coverage(rows: list[dict[str, str]]) -> float | None:
    values = [str(row.get("current_covered_q10_q90") or "").strip().upper() for row in rows]
    values = [value for value in values if value in {"TRUE", "FALSE"}]
    if not values:
        return None
    return sum(1 for value in values if value == "TRUE") / len(values)


def _error_share(rows: list[dict[str, str]], all_rows: list[dict[str, str]]) -> float | None:
    numerator = sum(_numbers(rows, "current_absolute_error"))
    denominator = sum(_numbers(all_rows, "current_absolute_error"))
    if denominator == 0:
        return None
    return numerator / denominator


def _mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _round_or_none(value: float | None, *, digits: int = 2) -> float | None:
    return round(float(value), digits) if value is not None else None


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _blank(value: Any) -> str:
    return "" if value is None else str(value)


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
