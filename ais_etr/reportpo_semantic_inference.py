from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any


SEMANTIC_INFERENCE_COLUMNS = (
    "feature_name",
    "raw_value",
    "inferred_label",
    "inference_confidence",
    "inference_basis",
    "source_rows",
    "source_share",
    "area_cluster_share",
    "top_areas",
    "top_offices",
    "top_etr_types",
    "median_restore_minutes",
    "mean_restore_minutes",
    "p90_restore_minutes",
    "webex_diagnostic_rows",
    "webex_truth_rows",
    "webex_mean_absolute_error",
    "webex_q10_q90_coverage",
    "recommended_use",
    "blocked_use",
    "caveat",
)

FIELD_DECISION_COLUMNS = (
    "field_name",
    "decision",
    "confidence",
    "evidence",
    "recommended_use",
    "blocked_use",
)

NORTH_NORTHEAST_PREFIXES = ("\u0e01\u0e1f\u0e09", "\u0e01\u0e1f\u0e19")
CENTRAL_SOUTH_PREFIXES = ("\u0e01\u0e1f\u0e01", "\u0e01\u0e1f\u0e15")


def build_reportpo_semantic_inference(
    features_csv: str | Path,
    diagnostics_csv: str | Path,
    output_csv: str | Path,
    field_decisions_csv: str | Path,
    markdown_output: str | Path | None = None,
) -> dict[str, Any]:
    feature_rows = _read_csv(features_csv)
    diagnostic_rows = _read_csv(diagnostics_csv)
    group_rows = _infer_group_values(feature_rows, diagnostic_rows)
    decision_rows = _field_decisions(group_rows)
    _write_csv(output_csv, SEMANTIC_INFERENCE_COLUMNS, group_rows)
    _write_csv(field_decisions_csv, FIELD_DECISION_COLUMNS, decision_rows)
    markdown_result = None
    if markdown_output:
        markdown_result = _write_markdown(
            markdown_output,
            features_csv,
            diagnostics_csv,
            group_rows,
            decision_rows,
        )
    return {
        "features_csv": str(features_csv),
        "diagnostics_csv": str(diagnostics_csv),
        "output_csv": str(output_csv),
        "field_decisions_csv": str(field_decisions_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "group_values": len(group_rows),
        "field_decisions": len(decision_rows),
        "inferred_values": sum(1 for row in group_rows if row["inference_confidence"] in {"high", "medium"}),
        "markdown": markdown_result,
    }


def _infer_group_values(
    feature_rows: list[dict[str, str]],
    diagnostic_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    groups = sorted({row.get("event_type") or "" for row in feature_rows if row.get("event_type")})
    total = len(feature_rows)
    output = []
    for group in groups:
        rows = [row for row in feature_rows if row.get("event_type") == group]
        durations = _float_values(row.get("reportpo_first_restore_minutes") for row in rows)
        area_counts = Counter(row.get("area") or "" for row in rows if row.get("area"))
        office_counts = Counter(row.get("office") or "" for row in rows if row.get("office"))
        etr_counts = Counter(row.get("etr_type_description") or "" for row in rows if row.get("etr_type_description"))
        cluster_label, cluster_share, cluster_basis = _infer_area_cluster(rows)
        diag = _diagnostic_stats(group, diagnostic_rows)
        output.append(
            {
                "feature_name": "ETR_OU.Group",
                "raw_value": group,
                "inferred_label": cluster_label,
                "inference_confidence": _confidence(cluster_share, len(rows)),
                "inference_basis": cluster_basis,
                "source_rows": str(len(rows)),
                "source_share": _fmt(len(rows) / total if total else None, digits=3),
                "area_cluster_share": _fmt(cluster_share, digits=3),
                "top_areas": _format_counter(area_counts),
                "top_offices": _format_counter(office_counts),
                "top_etr_types": _format_counter(etr_counts),
                "median_restore_minutes": _fmt(median(durations) if durations else None),
                "mean_restore_minutes": _fmt(_mean(durations)),
                "p90_restore_minutes": _fmt(_percentile(durations, 0.9)),
                "webex_diagnostic_rows": str(diag["rows"]),
                "webex_truth_rows": str(diag["truth_rows"]),
                "webex_mean_absolute_error": _fmt(diag["mean_absolute_error"]),
                "webex_q10_q90_coverage": _fmt(diag["q10_q90_coverage"], digits=3),
                "recommended_use": "shadow_challenger_categorical_or_geography_proxy_only",
                "blocked_use": "root_cause_label; customer_message_label; production_gate_feature",
                "caveat": "Inferred from distribution, not owner-confirmed; pilot Webex rows currently only cover one group code.",
            }
        )
    return sorted(output, key=lambda row: row["raw_value"])


def _infer_area_cluster(rows: list[dict[str, str]]) -> tuple[str, float, str]:
    areas = [row.get("area") or "" for row in rows if row.get("area")]
    if not areas:
        return "unknown", 0.0, "no_area_values"
    north_ne = sum(1 for value in areas if value.startswith(NORTH_NORTHEAST_PREFIXES))
    central_south = sum(1 for value in areas if value.startswith(CENTRAL_SOUTH_PREFIXES))
    total = len(areas)
    if north_ne >= central_south:
        share = north_ne / total
        label = "north_northeast_area_group"
        basis = "area values mostly start with PEA North/Northeast prefixes"
    else:
        share = central_south / total
        label = "central_south_area_group"
        basis = "area values mostly start with PEA Central/South prefixes"
    if share < 0.8:
        label = "mixed_area_group"
        basis = "area prefix distribution is mixed"
    return label, share, basis


def _diagnostic_stats(group: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    selected = [row for row in rows if row.get("reportpo_event_type") == group]
    truth_rows = [row for row in selected if _to_float(row.get("current_absolute_error")) is not None]
    errors = [_to_float(row.get("current_absolute_error")) for row in truth_rows]
    errors = [value for value in errors if value is not None]
    covered = [_to_bool(row.get("current_covered_q10_q90")) for row in truth_rows]
    covered = [value for value in covered if value is not None]
    return {
        "rows": len(selected),
        "truth_rows": len(truth_rows),
        "mean_absolute_error": _mean(errors),
        "q10_q90_coverage": (sum(1 for value in covered if value) / len(covered)) if covered else None,
    }


def _field_decisions(group_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    inferred_labels = "; ".join(
        f"{row['raw_value']}={row['inferred_label']} ({row['inference_confidence']})" for row in group_rows
    )
    pilot_covered_groups = [row["raw_value"] for row in group_rows if int(row.get("webex_diagnostic_rows") or "0") > 0]
    return [
        {
            "field_name": "ETR_OU.Group",
            "decision": "self_inferred_broad_area_group",
            "confidence": "medium",
            "evidence": inferred_labels,
            "recommended_use": "anonymous categorical/geography proxy in shadow challenger only",
            "blocked_use": "root cause, customer-facing label, or production gate without shadow validation",
        },
        {
            "field_name": "ETRtype.Description1/2",
            "decision": "readable_etr_process_label",
            "confidence": "medium",
            "evidence": "Values are readable process labels such as ETR RealTime, Fast ETR, Do Nothing.",
            "recommended_use": "diagnostics and leakage review",
            "blocked_use": "actual restoration truth or outage cause",
        },
        {
            "field_name": "cause_group/cause_code",
            "decision": "not_found_in_current_reportpo_feature_lane",
            "confidence": "high",
            "evidence": "Current 90,000-row feature scrape has empty cause_group and cause_code.",
            "recommended_use": "continue source discovery in eRespond/PO or another PowerBI visual",
            "blocked_use": "do not synthesize cause from ETR process labels",
        },
        {
            "field_name": "pilot_scope_group_coverage",
            "decision": "single_group_in_current_webex_matches",
            "confidence": "high" if len(pilot_covered_groups) == 1 else "medium",
            "evidence": "Current matched Webex diagnostics cover group codes: " + (", ".join(pilot_covered_groups) or "none"),
            "recommended_use": "do not expect ETR_OU.Group to improve the 3-district pilot unless wider-area training is evaluated",
            "blocked_use": "do not use as proof that cause/lifecycle gap is solved",
        },
    ]


def _write_markdown(
    path: str | Path,
    features_csv: str | Path,
    diagnostics_csv: str | Path,
    group_rows: list[dict[str, str]],
    decision_rows: list[dict[str, str]],
) -> dict[str, Any]:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# ReportPO Semantic Self-Inference",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Sources",
        "",
        f"- Feature CSV: `{features_csv}`",
        f"- Shadow diagnostics CSV: `{diagnostics_csv}`",
        "",
        "## Executive Conclusion",
        "",
        "- Owner confirmation is unavailable, so semantics below are inferred from observable PowerBI data distributions.",
        "- `ETR_OU.Group` is best interpreted as a broad area/workstream group, not outage cause or repair work type.",
        "- The two observed group codes split almost perfectly by PEA area prefixes: North/Northeast versus Central/South.",
        "- Current Webex matched diagnostics only cover one group code, so this field is not expected to materially improve the 3-district AIS pilot by itself.",
        "- Cause and operational lifecycle fields remain the missing high-value features for model improvement.",
        "",
        "## Inferred Group Code Map",
        "",
        _markdown_table(
            group_rows,
            (
                "raw_value",
                "inferred_label",
                "inference_confidence",
                "source_rows",
                "source_share",
                "area_cluster_share",
                "median_restore_minutes",
                "p90_restore_minutes",
                "webex_truth_rows",
            ),
        ),
        "",
        "## Field Decisions",
        "",
        _markdown_table(
            decision_rows,
            ("field_name", "decision", "confidence", "recommended_use", "blocked_use"),
        ),
        "",
        "## Operational Recommendation",
        "",
        "Proceed without owner input by treating `ETR_OU.Group` as an anonymous categorical/geography proxy in shadow-only experiments. Do not display it to customers and do not use it as a root-cause substitute. The next useful technical step is to run a shadow challenger that includes only as-of-notification safe features and reports pilot-scope metrics separately.",
        "",
        "## Privacy Note",
        "",
        "This report contains aggregate field distributions only. It omits message bodies, room identifiers, credentials, meter lists, and customer registration names.",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"output": str(output), "bytes": output.stat().st_size}


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: str | Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _float_values(values: Any) -> list[float]:
    output = []
    for value in values:
        parsed = _to_float(value)
        if parsed is not None:
            output.append(parsed)
    return sorted(output)


def _to_float(value: Any) -> float | None:
    try:
        text = "" if value is None else str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    text = "" if value is None else str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    index = int(max(0, min(len(values) - 1, round((len(values) - 1) * quantile))))
    return sorted(values)[index]


def _confidence(cluster_share: float, rows: int) -> str:
    if rows >= 1000 and cluster_share >= 0.95:
        return "high"
    if rows >= 100 and cluster_share >= 0.8:
        return "medium"
    return "low"


def _format_counter(counter: Counter[str], limit: int = 5) -> str:
    return "; ".join(f"{key}={value}" for key, value in counter.most_common(limit))


def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return ""
    return str(round(value, digits))


def _markdown_table(rows: list[dict[str, str]], columns: tuple[str, ...]) -> str:
    if not rows:
        return "_No rows._"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(_md_cell(row.get(column, "")) for column in columns) + " |" for row in rows]
    return "\n".join([header, sep, *body])


def _md_cell(value: str) -> str:
    return str(value).replace("|", "/").replace("\n", " ")
