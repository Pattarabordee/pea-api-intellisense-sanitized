from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


FIELD_AUDIT_COLUMNS = (
    "feature_name",
    "source_entity",
    "source_property",
    "category",
    "rows",
    "non_missing_rows",
    "missing_rate",
    "unique_values",
    "top_values",
    "readability_status",
    "unreadable_values",
    "webex_diagnostic_rows",
    "webex_truth_rows",
    "mean_absolute_error",
    "q10_q90_coverage",
    "model_action",
    "owner_question",
)

CANONICAL_FEATURES = {
    "event_type": {
        "source_entity": "ETR_OU",
        "source_property": "Group",
        "category": "event_type",
        "owner_question": "What are the business labels for ETR_OU.Group code values, and is this the correct outage/work type field?",
    },
    "work_type": {
        "source_entity": "ETR_OU",
        "source_property": "Group",
        "category": "event_type",
        "owner_question": "Is work type available as a separate event-level field, or should ETR_OU.Group be used after decoding?",
    },
    "event_status": {
        "source_entity": "ETRtype",
        "source_property": "Description2",
        "category": "status_notification",
        "owner_question": "Does ETRtype.Description2 describe the event status at notification time, or only the ETR process type?",
    },
    "etr_type": {
        "source_entity": "ETR_OU",
        "source_property": "ETRType",
        "category": "status_notification",
        "owner_question": "Confirm ETRType value meanings and whether they are available before first customer notification.",
    },
    "etr_type_description": {
        "source_entity": "ETRtype",
        "source_property": "Description1",
        "category": "status_notification",
        "owner_question": "Confirm whether Description1 is a stable ETR type label and not a post-event process outcome.",
    },
    "cause_group": {
        "source_entity": "unknown",
        "source_property": "cause_group",
        "category": "cause_weather",
        "owner_question": "Which ReportPO/eRespond field contains outage cause group at event grain?",
    },
    "cause_code": {
        "source_entity": "unknown",
        "source_property": "cause_code",
        "category": "cause_weather",
        "owner_question": "Which ReportPO/eRespond field contains outage cause code at event grain?",
    },
    "job_status_at_notification": {
        "source_entity": "pipeline",
        "source_property": "synthetic_assumption",
        "category": "lifecycle_time",
        "owner_question": "Which eRespond lifecycle field should define job status at Webex notification time?",
    },
    "feature_quality": {
        "source_entity": "pipeline",
        "source_property": "derived_quality",
        "category": "data_quality",
        "owner_question": "No owner action required; this is a derived quality flag.",
    },
}

MISSING_VALUES = {"", "-", "nan", "none", "null", "nat", "<missing>"}


def build_reportpo_feature_label_audit(
    features_csv: str | Path,
    diagnostics_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
) -> dict[str, Any]:
    feature_rows = _read_csv(features_csv)
    diagnostic_rows = _read_csv(diagnostics_csv)
    audit_rows = [
        _audit_feature(feature_name, metadata, feature_rows, diagnostic_rows)
        for feature_name, metadata in CANONICAL_FEATURES.items()
    ]
    _write_csv(output_csv, FIELD_AUDIT_COLUMNS, audit_rows)
    markdown_result = None
    if markdown_output:
        markdown_result = _write_markdown(
            markdown_output,
            features_csv,
            diagnostics_csv,
            audit_rows,
        )
    return {
        "features_csv": str(features_csv),
        "diagnostics_csv": str(diagnostics_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "features_profiled": len(audit_rows),
        "exclude_until_decoded": sum(1 for row in audit_rows if row["model_action"] == "exclude_until_decoded"),
        "diagnostic_only": sum(1 for row in audit_rows if row["model_action"] == "diagnostic_only"),
        "owner_source_gaps": sum(1 for row in audit_rows if row["model_action"] == "owner_source_gap"),
        "markdown": markdown_result,
    }


def _audit_feature(
    feature_name: str,
    metadata: dict[str, str],
    feature_rows: list[dict[str, str]],
    diagnostic_rows: list[dict[str, str]],
) -> dict[str, str]:
    values = [_clean(row.get(feature_name)) for row in feature_rows]
    non_missing_values = [value for value in values if value.lower() not in MISSING_VALUES]
    counts = Counter(non_missing_values)
    unreadable_values = sorted(value for value in counts if _is_unreadable_proxy(value))
    unreadable_rows = sum(counts[value] for value in unreadable_values)
    code_like_values = []
    if feature_name in {"event_type", "work_type"}:
        code_like_values = sorted(value for value in counts if _is_code_like_proxy(value))
    code_like_rows = sum(counts[value] for value in code_like_values)
    readability_status = _readability_status(feature_name, non_missing_values, unreadable_rows, code_like_rows)
    model_action = _model_action(feature_name, metadata, non_missing_values, readability_status)

    diag_stats = _diagnostic_stats(feature_name, diagnostic_rows)
    rows = len(feature_rows)
    return {
        "feature_name": feature_name,
        "source_entity": metadata["source_entity"],
        "source_property": metadata["source_property"],
        "category": metadata["category"],
        "rows": str(rows),
        "non_missing_rows": str(len(non_missing_values)),
        "missing_rate": _fmt(1.0 - (len(non_missing_values) / rows if rows else 0.0), digits=3),
        "unique_values": str(len(counts)),
        "top_values": _format_top_values(counts),
        "readability_status": readability_status,
        "unreadable_values": _format_top_values(
            Counter({value: counts[value] for value in sorted(set(unreadable_values + code_like_values))})
        ),
        "webex_diagnostic_rows": str(diag_stats["rows"]),
        "webex_truth_rows": str(diag_stats["truth_rows"]),
        "mean_absolute_error": _fmt(diag_stats["mean_absolute_error"]),
        "q10_q90_coverage": _fmt(diag_stats["q10_q90_coverage"], digits=3),
        "model_action": model_action,
        "owner_question": metadata["owner_question"],
    }


def _diagnostic_stats(feature_name: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    diagnostic_name = "reportpo_" + feature_name
    selected = [
        row
        for row in rows
        if _clean(row.get(diagnostic_name)).lower() not in MISSING_VALUES
    ]
    truth_rows = [
        row
        for row in selected
        if _to_float(row.get("current_absolute_error")) is not None
    ]
    errors = [_to_float(row.get("current_absolute_error")) for row in truth_rows]
    errors = [value for value in errors if value is not None]
    covered_values = [_to_bool(row.get("current_covered_q10_q90")) for row in truth_rows]
    covered_values = [value for value in covered_values if value is not None]
    coverage = None
    if covered_values:
        coverage = sum(1 for value in covered_values if value) / len(covered_values)
    return {
        "rows": len(selected),
        "truth_rows": len(truth_rows),
        "mean_absolute_error": _mean(errors),
        "q10_q90_coverage": coverage,
    }


def _model_action(
    feature_name: str,
    metadata: dict[str, str],
    non_missing_values: list[str],
    readability_status: str,
) -> str:
    if feature_name in {"cause_group", "cause_code"} and not non_missing_values:
        return "owner_source_gap"
    if metadata["source_entity"] == "pipeline":
        return "audit_only"
    if readability_status in {"encoded_or_proxy", "code_like_proxy"}:
        return "exclude_until_decoded"
    if feature_name in {"event_status", "etr_type", "etr_type_description"}:
        return "diagnostic_only"
    if non_missing_values:
        return "candidate_after_semantic_confirmation"
    return "owner_source_gap"


def _readability_status(
    feature_name: str,
    non_missing_values: list[str],
    unreadable_rows: int,
    code_like_rows: int,
) -> str:
    if not non_missing_values:
        return "missing"
    unreadable_ratio = unreadable_rows / len(non_missing_values)
    if unreadable_ratio >= 0.5:
        return "encoded_or_proxy"
    code_like_ratio = code_like_rows / len(non_missing_values)
    if feature_name in {"event_type", "work_type"} and code_like_ratio >= 0.5:
        return "code_like_proxy"
    if unreadable_rows:
        return "mixed"
    return "readable"


def _is_unreadable_proxy(value: str) -> bool:
    if not value:
        return False
    has_domain_char = False
    for char in value:
        if char.isascii():
            if char.isalnum():
                has_domain_char = True
            continue
        code = ord(char)
        if 0x0E00 <= code <= 0x0E7F:
            has_domain_char = True
            continue
        if char.isspace():
            continue
        return True
    return not has_domain_char


def _is_code_like_proxy(value: str) -> bool:
    text = value.strip()
    if not text or any(char.isspace() for char in text):
        return False
    if len(text) > 3:
        return False
    has_letter_or_digit = False
    for char in text:
        if char.isascii() and char.isalnum():
            has_letter_or_digit = True
            continue
        if 0x0E00 <= ord(char) <= 0x0E7F:
            has_letter_or_digit = True
            continue
        return False
    return has_letter_or_digit


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


def _write_markdown(
    path: str | Path,
    features_csv: str | Path,
    diagnostics_csv: str | Path,
    audit_rows: list[dict[str, str]],
) -> dict[str, Any]:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    action_counts = Counter(row["model_action"] for row in audit_rows)
    needs_owner = [
        row
        for row in audit_rows
        if row["model_action"] in {"exclude_until_decoded", "owner_source_gap", "candidate_after_semantic_confirmation"}
    ]
    candidate_rows = [
        row
        for row in audit_rows
        if row["model_action"] in {"diagnostic_only", "candidate_after_semantic_confirmation"}
    ]
    lines = [
        "# ReportPO Feature Label Audit",
        "",
        f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Sources",
        "",
        f"- Feature CSV: `{features_csv}`",
        f"- Shadow diagnostics CSV: `{diagnostics_csv}`",
        "",
        "## Summary",
        "",
        f"- Features profiled: {len(audit_rows)}",
        f"- Actions: {_format_counter(action_counts)}",
        "- This is a semantic readiness audit only. It does not promote any model and does not send AIS notifications.",
        "",
        "## Immediate Decision",
        "",
        "- Do not use `ETR_OU.Group` / canonical `event_type` or `work_type` for model training yet because the current values are encoded or proxy-like.",
        "- `ETRtype.Description1/2` can remain in diagnostics as readable ETR process labels, but they are not root-cause or crew-lifecycle fields.",
        "- Cause and work-type fields remain the biggest ReportPO/eRespond source gap for model improvement.",
        "",
        "## Field Readiness",
        "",
        _markdown_table(
            audit_rows,
            (
                "feature_name",
                "source_entity",
                "source_property",
                "readability_status",
                "model_action",
                "top_values",
            ),
        ),
        "",
        "## Owner Question Pack",
        "",
        _markdown_table(
            needs_owner,
            (
                "feature_name",
                "source_entity",
                "source_property",
                "owner_question",
            ),
        ),
        "",
        "## Safe Diagnostic Candidates",
        "",
        _markdown_table(
            candidate_rows,
            (
                "feature_name",
                "readability_status",
                "webex_truth_rows",
                "mean_absolute_error",
                "q10_q90_coverage",
            ),
        ),
        "",
        "## Privacy Note",
        "",
        "This report uses aggregate field values and redacted shadow diagnostics only. It does not include message bodies, room identifiers, credentials, meter lists, or customer registration names.",
    ]
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"output": str(output), "bytes": output.stat().st_size}


def _format_top_values(counter: Counter[str], limit: int = 5) -> str:
    if not counter:
        return ""
    return "; ".join(f"{value}={count}" for value, count in counter.most_common(limit))


def _format_counter(counter: Counter[str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(counter.items())) or "none"


def _markdown_table(rows: list[dict[str, str]], columns: tuple[str, ...]) -> str:
    if not rows:
        return "_No rows._"
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = []
    for row in rows:
        body.append("| " + " | ".join(_md_cell(row.get(column, "")) for column in columns) + " |")
    return "\n".join([header, sep, *body])


def _md_cell(value: str) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _to_float(value: Any) -> float | None:
    try:
        text = _clean(value)
        if text.lower() in MISSING_VALUES:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    text = _clean(value).lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return ""
    return str(round(value, digits))
