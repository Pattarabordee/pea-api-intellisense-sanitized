from __future__ import annotations

from collections import Counter
import csv
from pathlib import Path
from typing import Any


GATE_Q50_MAE_MAX = 16.0
GATE_COVERAGE_MIN = 0.75
GATE_COVERAGE_MAX = 0.90
MIN_SUSTAINED_ROWS_FOR_TUNING = 30


AUDIT_COLUMNS = [
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
    "duration_band",
    "evaluation_policy",
    "review_action",
    "current_p50",
    "current_q10",
    "current_q90",
    "current_absolute_error",
    "current_covered_q10_q90",
    "challenger_p50",
    "challenger_q10",
    "challenger_q90",
    "challenger_absolute_error",
    "challenger_covered_q10_q90",
    "absolute_error_delta_challenger_minus_current",
]


def build_truth_quality_audit(
    comparison_csv: str | Path,
    output_csv: str | Path,
    output_markdown: str | Path | None = None,
    *,
    micro_threshold_minutes: float = 1.0,
    short_threshold_minutes: float = 5.0,
) -> dict[str, Any]:
    source_rows = _read_csv(comparison_csv)
    audit_rows = audit_truth_quality(
        source_rows,
        micro_threshold_minutes=micro_threshold_minutes,
        short_threshold_minutes=short_threshold_minutes,
    )

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, AUDIT_COLUMNS, audit_rows)

    summary = summarize_truth_quality(
        source_rows,
        audit_rows,
        micro_threshold_minutes=micro_threshold_minutes,
        short_threshold_minutes=short_threshold_minutes,
    )
    markdown_path = Path(output_markdown) if output_markdown else None
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_markdown(summary, audit_rows), encoding="utf-8-sig")

    return {
        **summary,
        "output_csv": str(output),
        "output_markdown": str(markdown_path) if markdown_path else None,
        "comparison_csv": str(comparison_csv),
    }


def audit_truth_quality(
    rows: list[dict[str, str]],
    *,
    micro_threshold_minutes: float = 1.0,
    short_threshold_minutes: float = 5.0,
) -> list[dict[str, str]]:
    audit_rows = []
    for row in rows:
        actual = _to_float(row.get("actual_restoration_minutes"))
        if actual is None:
            continue
        policy = _evaluation_policy(actual, micro_threshold_minutes, short_threshold_minutes)
        audit_rows.append(
            {
                "event_id": row.get("event_id", ""),
                "webex_message_ref": row.get("webex_message_ref", ""),
                "event_time": row.get("event_time", ""),
                "district": row.get("district", ""),
                "device_type": row.get("device_type", ""),
                "device_id": row.get("device_id", ""),
                "feeder": row.get("feeder", ""),
                "match_level": row.get("match_level", ""),
                "affected_count": row.get("affected_count", ""),
                "actual_restoration_minutes": _fmt(actual),
                "duration_band": _duration_band(actual),
                "evaluation_policy": policy,
                "review_action": _review_action(policy),
                "current_p50": row.get("current_p50", ""),
                "current_q10": row.get("current_q10", ""),
                "current_q90": row.get("current_q90", ""),
                "current_absolute_error": row.get("current_absolute_error", ""),
                "current_covered_q10_q90": row.get("current_covered_q10_q90", ""),
                "challenger_p50": row.get("challenger_p50", ""),
                "challenger_q10": row.get("challenger_q10", ""),
                "challenger_q90": row.get("challenger_q90", ""),
                "challenger_absolute_error": row.get("challenger_absolute_error", ""),
                "challenger_covered_q10_q90": row.get("challenger_covered_q10_q90", ""),
                "absolute_error_delta_challenger_minus_current": row.get(
                    "absolute_error_delta_challenger_minus_current",
                    "",
                ),
            }
        )
    return audit_rows


def summarize_truth_quality(
    source_rows: list[dict[str, str]],
    audit_rows: list[dict[str, str]],
    *,
    micro_threshold_minutes: float = 1.0,
    short_threshold_minutes: float = 5.0,
) -> dict[str, Any]:
    policies = Counter(row["evaluation_policy"] for row in audit_rows)
    bands = Counter(row["duration_band"] for row in audit_rows)
    devices = Counter((row.get("device_type") or "<blank>") for row in audit_rows)
    feeders = Counter((row.get("feeder") or "<blank>") for row in audit_rows)
    micro_rows = [row for row in audit_rows if row["evaluation_policy"] == "momentary_micro_review"]
    review_rows = [
        row
        for row in audit_rows
        if row["evaluation_policy"] in {"momentary_micro_review", "short_interruption_review"}
    ]
    sustained_rows = [row for row in audit_rows if row["evaluation_policy"] == "sustained_outage_eligible"]
    sustained_metrics = _metrics(sustained_rows)
    return {
        "source_rows": len(source_rows),
        "with_truth": len(audit_rows),
        "micro_threshold_minutes": micro_threshold_minutes,
        "short_threshold_minutes": short_threshold_minutes,
        "policy_counts": dict(sorted(policies.items())),
        "quality_counts": dict(sorted(policies.items())),
        "duration_band_counts": dict(sorted(bands.items())),
        "top_device_types": dict(devices.most_common(8)),
        "top_feeders": dict(feeders.most_common(8)),
        "all_truth_metrics": _metrics(audit_rows),
        "sustained_truth_metrics": sustained_metrics,
        "usable_truth_metrics": sustained_metrics,
        "review_short_or_micro_metrics": _metrics(review_rows),
        "micro_error_share": _error_share(micro_rows, audit_rows, "current_absolute_error"),
        "sustained_rows": len(sustained_rows),
        "usable_rows": len(sustained_rows),
        "review_rows": len(review_rows),
        "sustained_gate_status": _gate_status(sustained_metrics),
        "recommendation": _recommendation(len(audit_rows), len(sustained_rows), len(review_rows), sustained_metrics),
    }


def _metrics(rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "rows": len(rows),
        "current_q50_mae_minutes": _round_or_none(_mean(_numbers(rows, "current_absolute_error"))),
        "challenger_q50_mae_minutes": _round_or_none(_mean(_numbers(rows, "challenger_absolute_error"))),
        "current_q10_q90_coverage": _round_or_none(_coverage(rows, "current_covered_q10_q90"), digits=3),
        "challenger_q10_q90_coverage": _round_or_none(_coverage(rows, "challenger_covered_q10_q90"), digits=3),
    }


def _render_markdown(summary: dict[str, Any], audit_rows: list[dict[str, str]]) -> str:
    all_metrics = summary["all_truth_metrics"]
    sustained_metrics = summary["sustained_truth_metrics"]
    review_metrics = summary["review_short_or_micro_metrics"]
    lines = [
        "# AIS ETR Sustained-Outage Evaluation Policy",
        "",
        "This report separates momentary/short interruptions from sustained outages before using shadow truth as a model accuracy gate.",
        "",
        "## Summary",
        "",
        f"- Source comparison rows: {summary['source_rows']}",
        f"- Rows with truth: {summary['with_truth']}",
        f"- Sustained outage eligible rows (>5 min): {summary['sustained_rows']}",
        f"- Rows needing micro/short restore review: {summary['review_rows']}",
        f"- Current-model error share from micro restores: {_blank_none(summary['micro_error_share'])}",
        f"- Sustained-only gate status: {summary['sustained_gate_status']}",
        "",
        "## Evaluation Policy Counts",
        "",
        "| Evaluation policy | Rows |",
        "| --- | ---: |",
    ]
    for label, count in summary["policy_counts"].items():
        lines.append(f"| {label} | {count} |")
    lines.extend(
        [
            "",
            "## Duration Bands",
            "",
            "| Duration band | Rows |",
            "| --- | ---: |",
        ]
    )
    for band, count in summary["duration_band_counts"].items():
        lines.append(f"| {band} | {count} |")
    lines.extend(
        [
            "",
            "## Metric Sensitivity",
            "",
            "| Segment | Rows | Current MAE | Current coverage | Challenger MAE | Challenger coverage |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
            _metric_row("All truth", all_metrics),
            _metric_row("Sustained only (>5 min)", sustained_metrics),
            _metric_row("Micro/short review (<=5 min)", review_metrics),
            "",
            "## Sustained-Only Production Gate",
            "",
            "| Gate | Value | Required | Status |",
            "| --- | ---: | ---: | --- |",
            f"| Sustained truth rows | {sustained_metrics['rows']} | >= {MIN_SUSTAINED_ROWS_FOR_TUNING} | {_row_count_status(sustained_metrics['rows'])} |",
            f"| Current q50 MAE | {_blank_none(sustained_metrics['current_q50_mae_minutes'])} | <= {GATE_Q50_MAE_MAX:g} | {_mae_status(sustained_metrics['current_q50_mae_minutes'])} |",
            f"| Current q10-q90 coverage | {_blank_none(sustained_metrics['current_q10_q90_coverage'])} | {GATE_COVERAGE_MIN:g}-{GATE_COVERAGE_MAX:g} | {_coverage_status(sustained_metrics['current_q10_q90_coverage'])} |",
            "",
            "## Top Review Candidates",
            "",
            "| Event ref | Time | Device | Feeder | Actual min | Current p50 | Error | Policy |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in _top_error_rows(audit_rows):
        device = row.get("device_id") or row.get("device_type") or ""
        lines.append(
            f"| {row.get('webex_message_ref', '')} | {row.get('event_time', '')} | {device} | "
            f"{row.get('feeder', '')} | {row.get('actual_restoration_minutes', '')} | "
            f"{row.get('current_p50', '')} | {row.get('current_absolute_error', '')} | "
            f"{row.get('evaluation_policy', '')} |"
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
            "- This report uses redacted message references from the comparison CSV.",
            "- Customer meter identifier lists, source chat text, space identifiers, credential values, and customer registration names are not included.",
            "- Treat every truth source as provisional until the source owner validates the join key, timestamp semantics, and sustained-outage policy.",
        ]
    )
    return "\n".join(lines)


def _metric_row(label: str, metrics: dict[str, Any]) -> str:
    return (
        f"| {label} | {metrics['rows']} | {_blank_none(metrics['current_q50_mae_minutes'])} | "
        f"{_blank_none(metrics['current_q10_q90_coverage'])} | "
        f"{_blank_none(metrics['challenger_q50_mae_minutes'])} | "
        f"{_blank_none(metrics['challenger_q10_q90_coverage'])} |"
    )


def _top_error_rows(rows: list[dict[str, str]], limit: int = 10) -> list[dict[str, str]]:
    return sorted(rows, key=lambda row: _to_float(row.get("current_absolute_error")) or -1, reverse=True)[:limit]


def _evaluation_policy(actual: float, micro_threshold: float, short_threshold: float) -> str:
    if actual < 0:
        return "invalid_negative"
    if actual > 1440:
        return "invalid_gt_24h"
    if actual <= micro_threshold:
        return "momentary_micro_review"
    if actual <= short_threshold:
        return "short_interruption_review"
    return "sustained_outage_eligible"


def _review_action(policy: str) -> str:
    if policy == "momentary_micro_review":
        return "Review as momentary/auto-reclose or ReportPO timestamp semantics before using for customer-facing ETR gates."
    if policy == "short_interruption_review":
        return "Review short restoration with AIS/operations before using for customer-facing ETR gates."
    if policy.startswith("invalid_"):
        return "Reject or repair before evaluation."
    return "Eligible for sustained-outage ETR evaluation gate."


def _duration_band(actual: float) -> str:
    if actual < 0:
        return "invalid_negative"
    if actual <= 1:
        return "0_1_min_micro"
    if actual <= 5:
        return "1_5_min_short"
    if actual <= 15:
        return "5_15_min"
    if actual <= 60:
        return "15_60_min"
    if actual <= 180:
        return "60_180_min"
    if actual <= 1440:
        return "180_1440_min"
    return "gt_1440_invalid"


def _recommendation(
    truth_rows: int,
    sustained_rows: int,
    review_rows: int,
    sustained_metrics: dict[str, Any],
) -> str:
    if truth_rows == 0:
        return "No truth rows are available; do not claim model accuracy."
    if sustained_rows < MIN_SUSTAINED_ROWS_FOR_TUNING:
        return (
            "Do not tune or promote the model yet. Sustained-outage truth is below 30 rows; "
            "keep micro/short interruptions in a review queue and wait for AIS site outage/restore truth."
        )
    if review_rows / truth_rows >= 0.5:
        return (
            "Separate micro/short restorations from customer-facing outages before model tuning. "
            "A single ETR model should not be judged on both momentary restores and sustained outages without a case-type feature."
        )
    if _gate_status(sustained_metrics) == "gate_pass":
        return "Sustained-outage truth passes the model gate; keep the challenger in shadow until human approval and AIS truth validation."
    return "Use the sustained-outage segment for provisional shadow evaluation, while keeping micro/short rows in a review queue."


def _gate_status(metrics: dict[str, Any]) -> str:
    rows = int(metrics.get("rows") or 0)
    mae = metrics.get("current_q50_mae_minutes")
    coverage = metrics.get("current_q10_q90_coverage")
    if rows < MIN_SUSTAINED_ROWS_FOR_TUNING:
        return "insufficient_sustained_truth"
    if mae is None or coverage is None:
        return "missing_metric"
    if float(mae) <= GATE_Q50_MAE_MAX and GATE_COVERAGE_MIN <= float(coverage) <= GATE_COVERAGE_MAX:
        return "gate_pass"
    return "gate_fail"


def _row_count_status(rows: int) -> str:
    return "pass" if rows >= MIN_SUSTAINED_ROWS_FOR_TUNING else "insufficient"


def _mae_status(value: Any) -> str:
    if value is None:
        return "missing"
    return "pass" if float(value) <= GATE_Q50_MAE_MAX else "fail"


def _coverage_status(value: Any) -> str:
    if value is None:
        return "missing"
    return "pass" if GATE_COVERAGE_MIN <= float(value) <= GATE_COVERAGE_MAX else "fail"


def _numbers(rows: list[dict[str, str]], column: str) -> list[float]:
    values = []
    for row in rows:
        value = _to_float(row.get(column))
        if value is not None:
            values.append(value)
    return values


def _coverage(rows: list[dict[str, str]], column: str) -> float | None:
    values = [str(row.get(column) or "").strip().upper() for row in rows]
    values = [value for value in values if value in {"TRUE", "FALSE"}]
    if not values:
        return None
    return sum(1 for value in values if value == "TRUE") / len(values)


def _error_share(numerator_rows: list[dict[str, str]], denominator_rows: list[dict[str, str]], column: str) -> float | None:
    numerator = sum(_numbers(numerator_rows, column))
    denominator = sum(_numbers(denominator_rows, column))
    if denominator == 0:
        return None
    return round(numerator / denominator, 3)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _round_or_none(value: float | None, *, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _blank_none(value: Any) -> str:
    return "" if value is None else str(value)


def _fmt(value: float) -> str:
    return str(round(float(value), 2))


def _to_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)
