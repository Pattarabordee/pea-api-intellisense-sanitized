from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Iterable


PROXY_CHALLENGER_COLUMNS = (
    "event_id",
    "webex_message_ref",
    "event_time",
    "district",
    "evaluation_scope",
    "device_type",
    "feeder",
    "actual_restoration_minutes",
    "current_p50",
    "current_q10",
    "current_q90",
    "current_absolute_error",
    "current_covered_q10_q90",
    "reportpo_feature_match_status",
    "reportpo_group_code",
    "reportpo_group_label",
    "proxy_source",
    "proxy_training_rows",
    "proxy_p50",
    "proxy_q10",
    "proxy_q90",
    "proxy_absolute_error",
    "proxy_covered_q10_q90",
    "error_delta_proxy_minus_current",
    "proxy_notes",
)

SUMMARY_COLUMNS = (
    "segment",
    "events",
    "truth_rows",
    "proxy_usable_rows",
    "current_q50_mae_on_proxy_subset",
    "current_q10_q90_coverage_on_proxy_subset",
    "proxy_q50_mae",
    "proxy_q10_q90_coverage",
    "status",
    "promotion_candidate",
    "notes",
)

PILOT_DISTRICTS = {"พังโคน", "วาริชภูมิ", "นิคมน้ำอูน"}


@dataclass(frozen=True)
class PriorRow:
    event_number: str
    event_start_time: datetime
    group_code: str
    actual_minutes: float


def build_reportpo_proxy_challenger(
    features_csv: str | Path,
    diagnostics_csv: str | Path,
    semantic_inference_csv: str | Path,
    output_csv: str | Path,
    summary_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    min_group_rows: int = 100,
    min_global_rows: int = 100,
) -> dict[str, Any]:
    if min_group_rows < 1 or min_global_rows < 1:
        raise ValueError("min_group_rows and min_global_rows must be at least 1")
    priors = _load_prior_rows(features_csv)
    labels = _load_group_labels(semantic_inference_csv)
    diagnostics = _read_csv(diagnostics_csv)
    rows = [
        _build_one_row(row, priors, labels, min_group_rows=min_group_rows, min_global_rows=min_global_rows)
        for row in diagnostics
    ]
    summary_rows = _summary_rows(rows)
    _write_csv(output_csv, PROXY_CHALLENGER_COLUMNS, rows)
    _write_csv(summary_csv, SUMMARY_COLUMNS, summary_rows)
    markdown_result = None
    if markdown_output:
        markdown_result = _write_markdown(markdown_output, features_csv, diagnostics_csv, rows, summary_rows)
    return {
        "features_csv": str(features_csv),
        "diagnostics_csv": str(diagnostics_csv),
        "semantic_inference_csv": str(semantic_inference_csv),
        "output_csv": str(output_csv),
        "summary_csv": str(summary_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "prior_rows": len(priors),
        "events": len(rows),
        "truth_rows": sum(1 for row in rows if row.get("actual_restoration_minutes")),
        "proxy_usable_rows": sum(1 for row in rows if row.get("proxy_absolute_error")),
        "summary_rows": len(summary_rows),
        "markdown": markdown_result,
    }


def _build_one_row(
    row: dict[str, str],
    priors: list[PriorRow],
    labels: dict[str, str],
    *,
    min_group_rows: int,
    min_global_rows: int,
) -> dict[str, str]:
    event_dt = _parse_dt(row.get("event_time"))
    actual = _to_float(row.get("actual_restoration_minutes"))
    group_code = (row.get("reportpo_event_type") or "").strip()
    current_p50 = _to_float(row.get("current_p50"))
    current_q10 = _to_float(row.get("current_q10"))
    current_q90 = _to_float(row.get("current_q90"))
    current_error = _to_float(row.get("current_absolute_error"))
    current_covered = row.get("current_covered_q10_q90") or _covered_text(actual, current_q10, current_q90)
    base = {column: "" for column in PROXY_CHALLENGER_COLUMNS}
    base.update(
        {
            "event_id": row.get("event_id") or "",
            "webex_message_ref": row.get("webex_message_ref") or "",
            "event_time": row.get("event_time") or "",
            "district": row.get("district") or "",
            "evaluation_scope": _evaluation_scope(row.get("district")),
            "device_type": row.get("device_type") or "",
            "feeder": row.get("feeder") or "",
            "actual_restoration_minutes": _fmt(actual),
            "current_p50": row.get("current_p50") or "",
            "current_q10": row.get("current_q10") or "",
            "current_q90": row.get("current_q90") or "",
            "current_absolute_error": _fmt(current_error),
            "current_covered_q10_q90": current_covered,
            "reportpo_feature_match_status": row.get("reportpo_feature_match_status") or "",
            "reportpo_group_code": group_code,
            "reportpo_group_label": labels.get(group_code, ""),
        }
    )
    if event_dt is None:
        base["proxy_source"] = "no_prediction"
        base["proxy_notes"] = "missing event_time"
        return base
    if actual is None:
        base["proxy_source"] = "no_prediction"
        base["proxy_notes"] = "missing actual restoration; not evaluated"
        return base

    prior_candidates = [prior for prior in priors if prior.event_start_time < event_dt]
    if not prior_candidates:
        base["proxy_source"] = "no_prediction"
        base["proxy_notes"] = "no time-respecting ReportPO prior rows before event"
        return base

    selected = []
    proxy_source = "global_time_prior"
    if group_code:
        group_candidates = [prior for prior in prior_candidates if prior.group_code == group_code]
        if len(group_candidates) >= min_group_rows:
            selected = group_candidates
            proxy_source = "reportpo_group_time_prior"
        else:
            base["proxy_notes"] = f"group_prior_rows={len(group_candidates)} below min_group_rows={min_group_rows}"
    if not selected:
        if len(prior_candidates) >= min_global_rows:
            selected = prior_candidates
        else:
            base["proxy_source"] = "no_prediction"
            base["proxy_notes"] = (
                (base.get("proxy_notes") + "; ") if base.get("proxy_notes") else ""
            ) + f"global_prior_rows={len(prior_candidates)} below min_global_rows={min_global_rows}"
            return base

    values = [prior.actual_minutes for prior in selected]
    q10 = _quantile(values, 0.1)
    p50 = _quantile(values, 0.5)
    q90 = _quantile(values, 0.9)
    proxy_error = abs(p50 - actual)
    base.update(
        {
            "proxy_source": proxy_source,
            "proxy_training_rows": str(len(values)),
            "proxy_p50": _fmt(p50),
            "proxy_q10": _fmt(q10),
            "proxy_q90": _fmt(q90),
            "proxy_absolute_error": _fmt(proxy_error),
            "proxy_covered_q10_q90": _covered_text(actual, q10, q90),
            "error_delta_proxy_minus_current": _fmt(proxy_error - current_error) if current_error is not None else "",
            "proxy_notes": base.get("proxy_notes") or "time_respecting_reportpo_proxy_prior; shadow_only",
        }
    )
    return base


def _summary_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    segments: list[tuple[str, list[dict[str, str]], str]] = [
        ("all_truth", rows, "All rows with truth; proxy metrics use only rows with proxy predictions."),
        ("pilot_3", [row for row in rows if row.get("evaluation_scope") == "pilot_3"], "Original AIS pilot districts only."),
        ("with_reportpo_group", [row for row in rows if row.get("proxy_source") == "reportpo_group_time_prior"], "Rows evaluated using ETR_OU.Group-specific prior."),
        ("global_fallback", [row for row in rows if row.get("proxy_source") == "global_time_prior"], "Rows evaluated using global time-respecting ReportPO prior."),
        ("no_proxy_prediction", [row for row in rows if row.get("proxy_source") == "no_prediction"], "Rows without sufficient safe proxy prior."),
    ]
    return [_one_summary_row(segment, segment_rows, notes) for segment, segment_rows, notes in segments]


def _one_summary_row(segment: str, rows: list[dict[str, str]], notes: str) -> dict[str, str]:
    truth_rows = [row for row in rows if _to_float(row.get("actual_restoration_minutes")) is not None]
    proxy_rows = [row for row in truth_rows if _to_float(row.get("proxy_absolute_error")) is not None]
    current_errors = [_to_float(row.get("current_absolute_error")) for row in proxy_rows]
    current_errors = [value for value in current_errors if value is not None]
    proxy_errors = [_to_float(row.get("proxy_absolute_error")) for row in proxy_rows]
    proxy_errors = [value for value in proxy_errors if value is not None]
    current_coverage = _coverage(proxy_rows, "current_covered_q10_q90")
    proxy_coverage = _coverage(proxy_rows, "proxy_covered_q10_q90")
    proxy_mae = mean(proxy_errors) if proxy_errors else None
    status = _gate_status(proxy_mae, proxy_coverage)
    return {
        "segment": segment,
        "events": str(len(rows)),
        "truth_rows": str(len(truth_rows)),
        "proxy_usable_rows": str(len(proxy_rows)),
        "current_q50_mae_on_proxy_subset": _fmt(mean(current_errors) if current_errors else None),
        "current_q10_q90_coverage_on_proxy_subset": _fmt(current_coverage, digits=3),
        "proxy_q50_mae": _fmt(proxy_mae),
        "proxy_q10_q90_coverage": _fmt(proxy_coverage, digits=3),
        "status": status,
        "promotion_candidate": "NO",
        "notes": notes,
    }


def _write_markdown(
    path: str | Path,
    features_csv: str | Path,
    diagnostics_csv: str | Path,
    rows: list[dict[str, str]],
    summary_rows: list[dict[str, str]],
) -> dict[str, Any]:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    source_counts = Counter(row.get("proxy_source") or "<blank>" for row in rows)
    lines = [
        "# ReportPO Proxy Shadow Challenger",
        "",
        "This report evaluates an anonymous ReportPO proxy prior. It is a shadow-only diagnostic and does not update the production model artifact.",
        "",
        "## Sources",
        "",
        f"- ReportPO features: `{features_csv}`",
        f"- Shadow diagnostics: `{diagnostics_csv}`",
        "",
        "## Method",
        "",
        "- Uses only ReportPO rows earlier than each Webex event time.",
        "- Uses `ETR_OU.Group` only as an anonymous broad geography/workstream proxy.",
        "- Falls back to a global time-respecting ReportPO prior when the group prior is missing or too sparse.",
        "- Does not synthesize cause, work type, or customer-facing labels.",
        "",
        "## Summary",
        "",
        "| Segment | Events | Truth rows | Proxy usable | Current MAE | Current coverage | Proxy MAE | Proxy coverage | Status | Promote? |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in summary_rows:
        lines.append(
            f"| {row['segment']} | {row['events']} | {row['truth_rows']} | {row['proxy_usable_rows']} | "
            f"{row['current_q50_mae_on_proxy_subset']} | {row['current_q10_q90_coverage_on_proxy_subset']} | "
            f"{row['proxy_q50_mae']} | {row['proxy_q10_q90_coverage']} | {row['status']} | {row['promotion_candidate']} |"
        )
    lines.extend(
        [
            "",
            "## Proxy Source Mix",
            "",
            "| Proxy source | Events |",
            "| --- | ---: |",
        ]
    )
    for source, count in sorted(source_counts.items()):
        lines.append(f"| {source} | {count} |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This challenger should pass only if pilot-scope q50 MAE is <=16 minutes and q10-q90 coverage is 0.75-0.90.",
            "- A global or area proxy can be useful as a baseline sanity check, but it is not a substitute for AIS active interval truth, cause, or lifecycle fields.",
            "- Production AIS send remains blocked.",
            "",
            "## Privacy Note",
            "",
            "This report omits message bodies, room identifiers, credentials, meter lists, and customer registration names.",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"output": str(output), "bytes": output.stat().st_size}


def _load_prior_rows(path: str | Path) -> list[PriorRow]:
    rows = []
    for row in _read_csv(path):
        actual = _to_float(row.get("reportpo_first_restore_minutes") or row.get("actual_restoration_minutes"))
        event_dt = _parse_dt(row.get("event_start_time"))
        if actual is None or event_dt is None:
            continue
        if actual <= 5 or actual > 1440:
            continue
        rows.append(
            PriorRow(
                event_number=row.get("event_number") or "",
                event_start_time=event_dt,
                group_code=row.get("event_type") or "",
                actual_minutes=actual,
            )
        )
    return sorted(rows, key=lambda item: item.event_start_time)


def _load_group_labels(path: str | Path) -> dict[str, str]:
    labels = {}
    for row in _read_csv(path):
        code = row.get("raw_value") or ""
        label = row.get("inferred_label") or ""
        if code and label:
            labels[code] = label
    return labels


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


def _evaluation_scope(district: str | None) -> str:
    text = (district or "").strip()
    return "pilot_3" if text in PILOT_DISTRICTS else "other_or_unknown"


def _parse_dt(value: Any) -> datetime | None:
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _to_float(value: Any) -> float | None:
    try:
        text = "" if value is None else str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _quantile(values: Iterable[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot compute quantile on an empty list")
    index = int(round((len(ordered) - 1) * quantile))
    index = max(0, min(len(ordered) - 1, index))
    return ordered[index]


def _coverage(rows: list[dict[str, str]], column: str) -> float | None:
    values = [row.get(column) for row in rows if row.get(column)]
    if not values:
        return None
    return sum(1 for value in values if str(value).strip().upper() == "TRUE") / len(values)


def _covered_text(actual: float | None, q10: float | None, q90: float | None) -> str:
    if actual is None or q10 is None or q90 is None:
        return ""
    return "TRUE" if q10 <= actual <= q90 else "FALSE"


def _gate_status(mae: float | None, coverage: float | None) -> str:
    if mae is None or coverage is None:
        return "insufficient_data"
    if mae <= 16 and 0.75 <= coverage <= 0.90:
        return "gate_pass"
    return "gate_fail"


def _fmt(value: float | None, digits: int = 2) -> str:
    if value is None:
        return ""
    return str(round(value, digits))
