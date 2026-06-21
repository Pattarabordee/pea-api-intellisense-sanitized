from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from statistics import median
from typing import Any


ENRICHED_COLUMNS = (
    "event_id",
    "webex_message_ref",
    "event_time",
    "district",
    "device_type",
    "device_id",
    "feeder",
    "match_level",
    "affected_count",
    "actual_restoration_minutes",
    "current_p50",
    "current_q10",
    "current_q90",
    "current_risk_level",
    "current_absolute_error",
    "current_covered_q10_q90",
    "reportpo_feature_match_status",
    "reportpo_event_number",
    "reportpo_delta_minutes",
    "reportpo_event_type",
    "reportpo_event_status",
    "reportpo_etr_type",
    "reportpo_etr_type_description",
    "reportpo_work_type",
    "reportpo_feature_quality",
    "diagnostic_bucket",
)

SEGMENT_COLUMNS = (
    "dimension",
    "segment",
    "events",
    "with_truth",
    "with_reportpo_feature",
    "mean_actual_minutes",
    "mean_p50_minutes",
    "mean_absolute_error",
    "median_absolute_error",
    "q10_q90_coverage",
    "high_error_events",
)


def build_reportpo_feature_diagnostics(
    comparison_csv: str | Path,
    feature_audit_csv: str | Path,
    output_csv: str | Path,
    segments_csv: str | Path,
    markdown_output: str | Path | None = None,
    high_error_threshold: float = 60.0,
    min_segment_truth: int = 3,
) -> dict[str, Any]:
    feature_by_ref = _load_features_by_redacted_ref(feature_audit_csv)
    enriched_rows: list[dict[str, str]] = []
    with Path(comparison_csv).open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            feature = feature_by_ref.get(row.get("webex_message_ref") or "", {})
            enriched_rows.append(_enriched_row(row, feature, high_error_threshold))

    segment_rows = _build_segments(enriched_rows, high_error_threshold, min_segment_truth)
    _write_csv(output_csv, ENRICHED_COLUMNS, enriched_rows)
    _write_csv(segments_csv, SEGMENT_COLUMNS, segment_rows)
    markdown_result = None
    if markdown_output:
        markdown_result = _write_markdown(
            markdown_output,
            comparison_csv,
            feature_audit_csv,
            enriched_rows,
            segment_rows,
            high_error_threshold,
            min_segment_truth,
        )
    truth_rows = [row for row in enriched_rows if _to_float(row.get("current_absolute_error")) is not None]
    feature_rows = [
        row
        for row in enriched_rows
        if row.get("reportpo_feature_match_status") in {"matched", "ambiguous"}
    ]
    return {
        "comparison_csv": str(comparison_csv),
        "feature_audit_csv": str(feature_audit_csv),
        "output_csv": str(output_csv),
        "segments_csv": str(segments_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "events": len(enriched_rows),
        "with_truth": len(truth_rows),
        "with_reportpo_feature": len(feature_rows),
        "segment_rows": len(segment_rows),
        "high_error_threshold": high_error_threshold,
        "min_segment_truth": min_segment_truth,
        "markdown": markdown_result,
    }


def _load_features_by_redacted_ref(path: str | Path) -> dict[str, dict[str, str]]:
    feature_path = Path(path)
    if not feature_path.exists():
        return {}
    output: dict[str, dict[str, str]] = {}
    with feature_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            ref = _redacted_ref(row.get("webex_message_id"))
            if not ref:
                continue
            current = output.get(ref)
            if current is None or _feature_rank(row) > _feature_rank(current):
                output[ref] = row
    return output


def _feature_rank(row: dict[str, str]) -> int:
    status = row.get("match_status") or ""
    if status == "matched":
        return 3
    if status == "ambiguous":
        return 2
    if row.get("event_number") or row.get("event_type") or row.get("event_status"):
        return 1
    return 0


def _enriched_row(comparison: dict[str, str], feature: dict[str, str], high_error_threshold: float) -> dict[str, str]:
    error = _to_float(comparison.get("current_absolute_error"))
    match_status = feature.get("match_status") or "missing_feature_row"
    bucket = "no_truth"
    if error is not None:
        bucket = "high_error" if error >= high_error_threshold else "normal_error"
    return {
        "event_id": comparison.get("event_id") or "",
        "webex_message_ref": comparison.get("webex_message_ref") or "",
        "event_time": comparison.get("event_time") or "",
        "district": comparison.get("district") or "",
        "device_type": comparison.get("device_type") or "",
        "device_id": comparison.get("device_id") or "",
        "feeder": comparison.get("feeder") or "",
        "match_level": comparison.get("match_level") or "",
        "affected_count": comparison.get("affected_count") or "",
        "actual_restoration_minutes": comparison.get("actual_restoration_minutes") or "",
        "current_p50": comparison.get("current_p50") or "",
        "current_q10": comparison.get("current_q10") or "",
        "current_q90": comparison.get("current_q90") or "",
        "current_risk_level": comparison.get("current_risk_level") or "",
        "current_absolute_error": comparison.get("current_absolute_error") or "",
        "current_covered_q10_q90": comparison.get("current_covered_q10_q90") or "",
        "reportpo_feature_match_status": match_status,
        "reportpo_event_number": feature.get("event_number") or "",
        "reportpo_delta_minutes": feature.get("delta_minutes") or "",
        "reportpo_event_type": feature.get("event_type") or "",
        "reportpo_event_status": feature.get("event_status") or "",
        "reportpo_etr_type": feature.get("etr_type") or "",
        "reportpo_etr_type_description": feature.get("etr_type_description") or "",
        "reportpo_work_type": feature.get("work_type") or "",
        "reportpo_feature_quality": feature.get("feature_quality") or "",
        "diagnostic_bucket": bucket,
    }


def _build_segments(
    rows: list[dict[str, str]],
    high_error_threshold: float,
    min_segment_truth: int,
) -> list[dict[str, str]]:
    dimensions = (
        ("reportpo_feature_match_status", "ReportPO feature match"),
        ("reportpo_event_type", "ReportPO event type"),
        ("reportpo_event_status", "ReportPO event status"),
        ("reportpo_etr_type_description", "ReportPO ETR type description"),
        ("reportpo_feature_quality", "ReportPO feature quality"),
        ("current_risk_level", "Current risk level"),
        ("device_type", "Webex device type"),
        ("match_level", "Protection match level"),
        ("diagnostic_bucket", "Diagnostic bucket"),
    )
    output: list[dict[str, str]] = []
    for field, label in dimensions:
        groups: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            segment = row.get(field) or "<missing>"
            groups.setdefault(segment, []).append(row)
        for segment, segment_rows in groups.items():
            truth_rows = [
                row
                for row in segment_rows
                if _to_float(row.get("current_absolute_error")) is not None
            ]
            if len(truth_rows) < min_segment_truth and field != "diagnostic_bucket":
                continue
            output.append(_segment_row(label, segment, segment_rows, truth_rows, high_error_threshold))
    return sorted(
        output,
        key=lambda row: (
            row["dimension"],
            -int(row["with_truth"] or "0"),
            row["segment"],
        ),
    )


def _segment_row(
    dimension: str,
    segment: str,
    rows: list[dict[str, str]],
    truth_rows: list[dict[str, str]],
    high_error_threshold: float,
) -> dict[str, str]:
    errors = [_to_float(row.get("current_absolute_error")) for row in truth_rows]
    errors = [value for value in errors if value is not None]
    actuals = [_to_float(row.get("actual_restoration_minutes")) for row in truth_rows]
    actuals = [value for value in actuals if value is not None]
    p50s = [_to_float(row.get("current_p50")) for row in truth_rows]
    p50s = [value for value in p50s if value is not None]
    covered_values = [_to_bool(row.get("current_covered_q10_q90")) for row in truth_rows]
    covered_values = [value for value in covered_values if value is not None]
    feature_count = sum(
        1 for row in rows if row.get("reportpo_feature_match_status") in {"matched", "ambiguous"}
    )
    return {
        "dimension": dimension,
        "segment": segment,
        "events": str(len(rows)),
        "with_truth": str(len(truth_rows)),
        "with_reportpo_feature": str(feature_count),
        "mean_actual_minutes": _fmt(_mean(actuals)),
        "mean_p50_minutes": _fmt(_mean(p50s)),
        "mean_absolute_error": _fmt(_mean(errors)),
        "median_absolute_error": _fmt(median(errors) if errors else None),
        "q10_q90_coverage": _fmt(_mean([1.0 if value else 0.0 for value in covered_values]), digits=3),
        "high_error_events": str(sum(1 for value in errors if value >= high_error_threshold)),
    }


def _write_markdown(
    path: str | Path,
    comparison_csv: str | Path,
    feature_audit_csv: str | Path,
    enriched_rows: list[dict[str, str]],
    segment_rows: list[dict[str, str]],
    high_error_threshold: float,
    min_segment_truth: int,
) -> dict[str, Any]:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    truth_rows = [row for row in enriched_rows if _to_float(row.get("current_absolute_error")) is not None]
    feature_rows = [
        row for row in enriched_rows if row.get("reportpo_feature_match_status") in {"matched", "ambiguous"}
    ]
    top_error_segments = sorted(
        [row for row in segment_rows if int(row.get("with_truth") or "0") >= min_segment_truth],
        key=lambda row: float(row.get("mean_absolute_error") or "0"),
        reverse=True,
    )[:12]
    lines = [
        "# ReportPO Feature Error Diagnostics",
        "",
        "## Sources",
        "",
        f"- Shadow comparison: `{comparison_csv}`",
        f"- ReportPO feature audit: `{feature_audit_csv}`",
        "",
        "## Summary",
        "",
        f"- Events: {len(enriched_rows)}",
        f"- Events with truth: {len(truth_rows)}",
        f"- Events with ReportPO feature match/ambiguous row: {len(feature_rows)}",
        f"- High-error threshold: {high_error_threshold:g} minutes",
        f"- Minimum truth rows per segment: {min_segment_truth}",
        "",
        "## Highest Error Segments",
        "",
        _markdown_table(
            top_error_segments,
            (
                "dimension",
                "segment",
                "with_truth",
                "mean_absolute_error",
                "q10_q90_coverage",
                "high_error_events",
            ),
        ),
        "",
        "## Interpretation",
        "",
        "- Use this as an error diagnostic, not as model promotion evidence.",
        "- Segments with sparse truth rows are suppressed from the main segment table except diagnostic buckets.",
        "- ReportPO feature rows are joined through redacted Webex message refs; this report does not include raw Webex ids, raw message text, room identifiers, meter lists, or customer registration names.",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"output": str(output), "bytes": output.stat().st_size}


def _write_csv(path: str | Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _markdown_table(rows: list[dict[str, str]], columns: tuple[str, ...]) -> str:
    if not rows:
        return "_No rows._"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(str(row.get(column, "")).replace("|", "/") for column in columns) + " |")
    return "\n".join([header, sep, *body])


def _redacted_ref(value: str | None) -> str:
    if not value:
        return ""
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"msg-{digest}"


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


def _to_bool(value: Any) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return ""
    return str(round(float(value), digits))
