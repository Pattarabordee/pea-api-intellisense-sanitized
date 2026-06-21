from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any


ERROR_SEGMENT_COLUMNS = (
    "segment_type",
    "segment",
    "incidents",
    "mean_actual_minutes",
    "median_actual_minutes",
    "mean_p50_minutes",
    "mean_absolute_error_minutes",
    "total_absolute_error_minutes",
    "share_of_total_absolute_error",
    "q10_q90_coverage",
    "long_gt_180_rows",
)


def build_shadow_error_diagnostics(
    comparison_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
) -> dict[str, Any]:
    rows = [row for row in _read_csv(comparison_csv) if _to_float(row.get("actual_restoration_minutes")) is not None]
    segment_rows = []
    for segment_type, key_fn in (
        ("duration_band", lambda row: _duration_band(_to_float(row.get("actual_restoration_minutes")) or 0)),
        ("feeder", lambda row: row.get("feeder") or "<blank>"),
        ("device_type", lambda row: row.get("device_type") or "<blank>"),
        ("affected_count", lambda row: row.get("affected_count") or "<blank>"),
    ):
        segment_rows.extend(_segment_rows(rows, segment_type, key_fn))

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, segment_rows)

    summary = _summary(rows, segment_rows)
    if markdown_output:
        markdown = Path(markdown_output)
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(_render_markdown(summary, segment_rows), encoding="utf-8-sig")

    return {
        **summary,
        "comparison_csv": str(comparison_csv),
        "output_csv": str(output),
        "markdown_output": str(markdown_output) if markdown_output else None,
    }


def _segment_rows(rows: list[dict[str, str]], segment_type: str, key_fn) -> list[dict[str, str]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        groups[str(key_fn(row))].append(row)
    total_error = sum(_to_float(row.get("current_absolute_error")) or 0 for row in rows)
    output = []
    for segment, group in groups.items():
        actual = [_to_float(row.get("actual_restoration_minutes")) or 0 for row in group]
        p50 = [_to_float(row.get("current_p50")) or 0 for row in group]
        errors = [_to_float(row.get("current_absolute_error")) or 0 for row in group]
        total = sum(errors)
        covered = [str(row.get("current_covered_q10_q90") or "").strip().upper() for row in group]
        covered = [value for value in covered if value]
        output.append(
            {
                "segment_type": segment_type,
                "segment": segment,
                "incidents": str(len(group)),
                "mean_actual_minutes": _fmt(mean(actual)),
                "median_actual_minutes": _fmt(median(actual)),
                "mean_p50_minutes": _fmt(mean(p50)),
                "mean_absolute_error_minutes": _fmt(mean(errors)),
                "total_absolute_error_minutes": _fmt(total),
                "share_of_total_absolute_error": _fmt(total / total_error if total_error else 0, digits=3),
                "q10_q90_coverage": _fmt(sum(1 for value in covered if value == "TRUE") / len(covered), digits=3)
                if covered
                else "",
                "long_gt_180_rows": str(sum(1 for value in actual if value > 180)),
            }
        )
    return sorted(
        output,
        key=lambda row: (row["segment_type"], -float(row["total_absolute_error_minutes"] or 0), row["segment"]),
    )


def _summary(rows: list[dict[str, str]], segment_rows: list[dict[str, str]]) -> dict[str, Any]:
    errors = [_to_float(row.get("current_absolute_error")) or 0 for row in rows]
    actual = [_to_float(row.get("actual_restoration_minutes")) or 0 for row in rows]
    covered = [str(row.get("current_covered_q10_q90") or "").strip().upper() for row in rows]
    coverage = sum(1 for value in covered if value == "TRUE") / len(covered) if covered else None
    duration_segments = [row for row in segment_rows if row["segment_type"] == "duration_band"]
    top_feeders = [row for row in segment_rows if row["segment_type"] == "feeder"][:8]
    return {
        "incidents": len(rows),
        "mean_absolute_error_minutes": round(mean(errors), 2) if errors else None,
        "q10_q90_coverage": round(float(coverage), 3) if coverage is not None else None,
        "mean_actual_minutes": round(mean(actual), 2) if actual else None,
        "median_actual_minutes": round(median(actual), 2) if actual else None,
        "long_gt_180_rows": sum(1 for value in actual if value > 180),
        "duration_segments": duration_segments,
        "top_feeders_by_error": top_feeders,
        "dominant_driver": _dominant_driver(duration_segments),
    }


def _dominant_driver(duration_segments: list[dict[str, str]]) -> str:
    long_row = next((row for row in duration_segments if row.get("segment") == ">180"), None)
    if long_row:
        share = _to_float(long_row.get("share_of_total_absolute_error")) or 0
        if share >= 0.5:
            return f">180 minute incidents drive {share:.1%} of total absolute error"
    return "No single duration band explains at least half of total absolute error"


def _render_markdown(summary: dict[str, Any], segment_rows: list[dict[str, str]]) -> str:
    lines = [
        "# AIS Incident Error Diagnostics",
        "",
        "This diagnostic explains why the AIS incident-level model gate is failing. It uses incident-level shadow truth and does not expose PEANO lists, raw Webex text, room IDs, or customer registration names.",
        "",
        "## Summary",
        "",
        f"- Incidents with truth: {summary['incidents']}",
        f"- Current q50 MAE: {summary['mean_absolute_error_minutes']} minutes",
        f"- Current q10-q90 coverage: {summary['q10_q90_coverage']}",
        f"- Mean actual restoration: {summary['mean_actual_minutes']} minutes",
        f"- Median actual restoration: {summary['median_actual_minutes']} minutes",
        f"- Incidents >180 minutes: {summary['long_gt_180_rows']}",
        f"- Dominant driver: {summary['dominant_driver']}",
        "",
        "## Error By Duration Band",
        "",
        "| Duration band | Incidents | Mean actual | Mean p50 | Mean error | Share of total error | Coverage |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in [row for row in segment_rows if row["segment_type"] == "duration_band"]:
        lines.append(
            f"| {row['segment']} | {row['incidents']} | {row['mean_actual_minutes']} | "
            f"{row['mean_p50_minutes']} | {row['mean_absolute_error_minutes']} | "
            f"{row['share_of_total_absolute_error']} | {row['q10_q90_coverage']} |"
        )
    lines.extend(
        [
            "",
            "## Top Feeders By Error Contribution",
            "",
            "| Feeder | Incidents | Mean actual | Mean error | Share of total error | Long >180 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in [row for row in segment_rows if row["segment_type"] == "feeder"][:10]:
        lines.append(
            f"| {row['segment']} | {row['incidents']} | {row['mean_actual_minutes']} | "
            f"{row['mean_absolute_error_minutes']} | {row['share_of_total_absolute_error']} | "
            f"{row['long_gt_180_rows']} |"
        )
    lines.extend(
        [
            "",
            "## Implication",
            "",
            "- The current model is not merely under-covered; its p50 is too low for long AIS site-power interruptions.",
            "- Repeated Webex message clustering helped, but long-duration events still dominate total error.",
            "- The next model step should add an AIS-history challenger and a long-outage risk feature or live AIS alarm state before promotion is considered.",
        ]
    )
    return "\n".join(lines) + "\n"


def _duration_band(value: float) -> str:
    if value <= 15:
        return "5-15"
    if value <= 60:
        return "15-60"
    if value <= 180:
        return "60-180"
    return ">180"


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ERROR_SEGMENT_COLUMNS))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in ERROR_SEGMENT_COLUMNS} for row in rows)


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fmt(value: float, *, digits: int = 2) -> str:
    return f"{value:.{digits}f}".rstrip("0").rstrip(".")
