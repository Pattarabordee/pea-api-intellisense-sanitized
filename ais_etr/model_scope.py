from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

from .db import RuntimeDb
from .matcher import ProtectionMatcher
from .model import EtrPredictor, evaluate_time_holdout, fit_quantile_baseline, load_training_frame, _row_prediction
from .schemas import OutageDevice, OutageEvent
from .utils import normalize_feeder


MAPPING_COLUMNS = ["station_prefix", "district", "scope", "status", "notes"]
COMPARISON_COLUMNS = [
    "model_variant",
    "evaluation_segment",
    "train_scope",
    "eval_scope",
    "rows_train",
    "rows_test",
    "q50_mae_minutes",
    "q10_q90_coverage",
    "status",
    "promotion_candidate",
    "notes",
]
REVIEW_COLUMNS = [
    "station_prefix",
    "district",
    "scope",
    "status",
    "training_rows",
    "runtime_events",
    "target_median_minutes",
    "target_p90_minutes",
    "top_feeders",
    "top_site_detail",
    "top_op_device_site_id",
    "top_affected_site_id",
    "recommendation",
    "review_note",
]
SHADOW_MODEL_COMPARISON_COLUMNS = [
    "event_id",
    "webex_message_ref",
    "event_time",
    "district",
    "device_type",
    "device_id",
    "feeder",
    "match_level",
    "match_confidence",
    "affected_count",
    "actual_restoration_minutes",
    "truth_source",
    "current_model_version",
    "current_p50",
    "current_q10",
    "current_q90",
    "current_risk_level",
    "current_absolute_error",
    "current_covered_q10_q90",
    "challenger_model_version",
    "challenger_p50",
    "challenger_q10",
    "challenger_q90",
    "challenger_risk_level",
    "challenger_absolute_error",
    "challenger_covered_q10_q90",
    "p50_delta_challenger_minus_current",
    "absolute_error_delta_challenger_minus_current",
]

DEFAULT_STATION_MAPPING = {
    "PFA": {"district": "พังโคน", "scope": "pilot_3", "status": "approved", "notes": "PEA GIS/API known station prefix."},
    "WDA": {"district": "วาริชภูมิ", "scope": "pilot_3", "status": "approved", "notes": "PEA GIS/API known station prefix."},
    "WWA": {"district": "วานรนิวาส", "scope": "expanded_6", "status": "approved", "notes": "Expanded Webex room station prefix."},
    "SEK": {"district": "เซกา", "scope": "expanded_6", "status": "approved", "notes": "Expanded Webex room station prefix."},
    "BDH": {"district": "บ้านดุง", "scope": "expanded_6", "status": "approved", "notes": "Expanded Webex room station prefix."},
    "XIA": {"district": "unknown", "scope": "unknown", "status": "pending", "notes": "Observed in GIS distance references; needs owner review if used."},
}


def build_station_district_mapping(
    db_path: str | Path,
    event_file: str | Path,
    etr_files: list[str | Path] | tuple[str | Path, ...],
    distance_file: str | Path,
    output_csv: str | Path,
) -> dict[str, Any]:
    prefixes = set(_runtime_station_prefixes(db_path))
    try:
        frame = load_training_frame(event_file, etr_files, distance_file)
        prefixes.update(_prefix_from_feeder(value) for value in frame.get("Feeder", []) if _prefix_from_feeder(value))
    except Exception:
        frame = pd.DataFrame()

    rows = []
    for prefix in sorted(prefixes):
        default = DEFAULT_STATION_MAPPING.get(
            prefix,
            {"district": "unknown", "scope": "unknown", "status": "pending", "notes": "Needs station/district owner review."},
        )
        rows.append({"station_prefix": prefix, **default})

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, MAPPING_COLUMNS, rows)
    counts = Counter(row["scope"] for row in rows)
    status_counts = Counter(row["status"] for row in rows)
    return {
        "output_csv": str(output),
        "station_prefixes": len(rows),
        "scope_counts": dict(sorted(counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "training_rows_checked": int(len(frame)),
    }


def build_model_scope_comparison(
    event_file: str | Path,
    etr_files: list[str | Path] | tuple[str | Path, ...],
    distance_file: str | Path,
    mapping_csv: str | Path,
    output_csv: str | Path,
    output_markdown: str | Path | None = None,
) -> dict[str, Any]:
    frame = load_training_frame(event_file, etr_files, distance_file)
    mapping_rows = _read_csv(mapping_csv)
    rows = compare_model_scopes(frame, mapping_rows)
    mapping_ready = _mapping_ready(mapping_rows)
    if not mapping_ready:
        for row in rows:
            if row.get("promotion_candidate") == "YES":
                row["promotion_candidate"] = "NO"
                row["notes"] = (row.get("notes") or "") + "; blocked by pending/unknown station mapping"
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, COMPARISON_COLUMNS, rows)

    markdown_path = Path(output_markdown) if output_markdown else None
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_markdown(rows, mapping_rows, mapping_ready=mapping_ready), encoding="utf-8-sig")

    return {
        "output_csv": str(output),
        "output_markdown": str(markdown_path) if markdown_path else None,
        "comparison_rows": len(rows),
        "promotion_candidate": mapping_ready and any(row.get("promotion_candidate") == "YES" for row in rows),
        "mapping_ready": mapping_ready,
        "mapping_status_counts": dict(sorted(Counter(row.get("status") or "" for row in mapping_rows).items())),
    }


def build_station_mapping_review(
    db_path: str | Path,
    event_file: str | Path,
    etr_files: list[str | Path] | tuple[str | Path, ...],
    distance_file: str | Path,
    mapping_csv: str | Path,
    output_csv: str | Path,
    output_markdown: str | Path | None = None,
) -> dict[str, Any]:
    frame = load_training_frame(event_file, etr_files, distance_file)
    mapping_rows = _read_csv(mapping_csv)
    runtime_counts = _runtime_station_prefix_counts(db_path)
    rows = review_station_mapping(frame, mapping_rows, runtime_counts)

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, REVIEW_COLUMNS, rows)

    markdown_path = Path(output_markdown) if output_markdown else None
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_review_markdown(rows), encoding="utf-8-sig")

    return {
        "output_csv": str(output),
        "output_markdown": str(markdown_path) if markdown_path else None,
        "review_rows": len(rows),
        "recommendation_counts": dict(sorted(Counter(row.get("recommendation") or "" for row in rows).items())),
        "pending_or_unknown": [
            row["station_prefix"]
            for row in rows
            if row.get("recommendation") == "owner_review_required"
        ],
    }


def train_scope_challenger_model(
    event_file: str | Path,
    etr_files: list[str | Path] | tuple[str | Path, ...],
    distance_file: str | Path,
    mapping_csv: str | Path,
    output_model: str | Path,
    output_markdown: str | Path | None = None,
    train_scope: str = "expanded_6",
) -> dict[str, Any]:
    frame = load_training_frame(event_file, etr_files, distance_file)
    mapping_rows = _read_csv(mapping_csv)
    model, summary = fit_scope_challenger_model(frame, mapping_rows, train_scope=train_scope)
    output = Path(output_model)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    markdown_path = Path(output_markdown) if output_markdown else None
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_challenger_markdown(summary, output), encoding="utf-8-sig")

    return {
        **summary,
        "output_model": str(output),
        "output_markdown": str(markdown_path) if markdown_path else None,
    }


def fit_scope_challenger_model(
    frame: pd.DataFrame,
    mapping_rows: list[dict[str, str]],
    train_scope: str = "expanded_6",
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not _mapping_ready(mapping_rows):
        raise ValueError("Station mapping has pending or unknown prefixes; review mapping before training a challenger")
    scoped = _scope_filtered_frame(frame, mapping_rows, train_scope=train_scope)
    if scoped.empty:
        raise ValueError(f"No training rows available for train_scope={train_scope}")
    model = fit_quantile_baseline(scoped)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    model["model_version"] = f"shadow-challenger-{train_scope}-{stamp}"
    model["model_role"] = "shadow_challenger"
    model["scope_filter"] = {
        "train_scope": train_scope,
        "included_scopes": _included_scopes(train_scope),
        "mapping_ready": True,
        "approved_station_prefixes": sorted(
            str(row.get("station_prefix") or "").strip().upper()
            for row in mapping_rows
            if str(row.get("status") or "").strip().lower() == "approved"
        ),
    }
    metrics = evaluate_time_holdout(scoped)
    model["metrics"] = metrics
    model["row_count"] = int(len(scoped))
    scope_counts = scoped["scope"].fillna("unknown").value_counts().to_dict()
    station_counts = scoped["station_prefix"].fillna("unknown").value_counts().to_dict()
    summary = {
        "model_version": model["model_version"],
        "estimator": model["estimator"],
        "status": metrics.get("status", "unknown"),
        "train_scope": train_scope,
        "included_scopes": _included_scopes(train_scope),
        "rows_train_full": int(len(scoped)),
        "scope_counts": {str(key): int(value) for key, value in sorted(scope_counts.items())},
        "station_counts": {str(key): int(value) for key, value in sorted(station_counts.items())},
        "metrics": metrics,
        "production_ready": metrics.get("status") == "gate_pass",
    }
    return model, summary


def build_shadow_model_comparison(
    db_path: str | Path,
    current_model_path: str | Path,
    challenger_model_path: str | Path,
    output_csv: str | Path,
    output_markdown: str | Path | None = None,
    truth_mapping_path: str | Path | None = None,
) -> dict[str, Any]:
    current = EtrPredictor.load(current_model_path)
    challenger = EtrPredictor.load(challenger_model_path)
    truth = _load_simple_truth_mapping(truth_mapping_path)
    rows = compare_shadow_models(db_path, current, challenger, truth)

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output, SHADOW_MODEL_COMPARISON_COLUMNS, rows)

    summary = _shadow_model_comparison_summary(rows, current.model, challenger.model)
    markdown_path = Path(output_markdown) if output_markdown else None
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_shadow_model_comparison_markdown(summary), encoding="utf-8-sig")

    return {
        **summary,
        "output_csv": str(output),
        "output_markdown": str(markdown_path) if markdown_path else None,
        "truth_mapping": str(truth_mapping_path) if truth_mapping_path else None,
    }


def compare_shadow_models(
    db_path: str | Path,
    current: EtrPredictor,
    challenger: EtrPredictor,
    truth_mapping: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    events = _runtime_events(db_path)
    matcher = ProtectionMatcher(RuntimeDb(db_path).load_customer_assets())
    truth_mapping = truth_mapping or {}
    rows: list[dict[str, str]] = []
    for event in events:
        match_result = matcher.match(event)
        current_prediction = current.predict(event, match_result)
        challenger_prediction = challenger.predict(event, match_result)
        truth = truth_mapping.get(event.webex_message_id or "", {})
        actual = _to_float(truth.get("actual_restoration_minutes"))
        current_error = abs(current_prediction.etr_minutes_p50 - actual) if actual is not None else None
        challenger_error = abs(challenger_prediction.etr_minutes_p50 - actual) if actual is not None else None
        rows.append(
            {
                "event_id": event.event_id,
                "webex_message_ref": _redacted_ref(event.webex_message_id),
                "event_time": event.event_time or "",
                "district": event.district or "",
                "device_type": event.outage_device.device_type or "",
                "device_id": event.outage_device.device_id or "",
                "feeder": event.outage_device.feeder or "",
                "match_level": match_result.match_level or "",
                "match_confidence": _fmt(match_result.match_confidence, digits=3),
                "affected_count": str(len(match_result.matches)),
                "actual_restoration_minutes": _fmt(actual) if actual is not None else "",
                "truth_source": str(truth.get("truth_source") or ""),
                "current_model_version": current_prediction.model_version,
                "current_p50": _fmt(current_prediction.etr_minutes_p50),
                "current_q10": _fmt(current_prediction.q10),
                "current_q90": _fmt(current_prediction.q90),
                "current_risk_level": current_prediction.risk_level,
                "current_absolute_error": _fmt(current_error) if current_error is not None else "",
                "current_covered_q10_q90": _covered_text(actual, current_prediction.q10, current_prediction.q90),
                "challenger_model_version": challenger_prediction.model_version,
                "challenger_p50": _fmt(challenger_prediction.etr_minutes_p50),
                "challenger_q10": _fmt(challenger_prediction.q10),
                "challenger_q90": _fmt(challenger_prediction.q90),
                "challenger_risk_level": challenger_prediction.risk_level,
                "challenger_absolute_error": _fmt(challenger_error) if challenger_error is not None else "",
                "challenger_covered_q10_q90": _covered_text(actual, challenger_prediction.q10, challenger_prediction.q90),
                "p50_delta_challenger_minus_current": _fmt(
                    challenger_prediction.etr_minutes_p50 - current_prediction.etr_minutes_p50
                ),
                "absolute_error_delta_challenger_minus_current": (
                    _fmt(challenger_error - current_error)
                    if challenger_error is not None and current_error is not None
                    else ""
                ),
            }
        )
    return rows


def compare_model_scopes(frame: pd.DataFrame, mapping_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    enriched = _enrich_scope(frame, mapping_rows)
    approved = enriched[
        (enriched["mapping_status"] == "approved")
        & (enriched["scope"].isin(["pilot_3", "expanded_6"]))
    ].copy()
    pilot = approved[approved["scope"] == "pilot_3"].copy()
    expanded = approved[approved["scope"].isin(["pilot_3", "expanded_6"])].copy()

    rows: list[dict[str, str]] = []
    a = _time_holdout_row("A", "pilot_3", "pilot_3", pilot, "pilot_3")
    rows.append(a)
    b = _time_holdout_row("B", "expanded_6", "expanded_6", expanded, "expanded_6")
    rows.append(b)

    b_model, b_test, b_train_count = _fit_holdout_model(expanded)
    if b_model is None or b_test is None:
        rows.append(_insufficient_row("C", "pilot_3", "expanded_6", "pilot_3", 0, "expanded training pool has insufficient data"))
    else:
        pilot_segment = b_test[b_test["scope"] == "pilot_3"].copy()
        expanded_only = b_test[b_test["scope"] == "expanded_6"].copy()
        c_pilot = _evaluate_existing_model_row(
            "C",
            "pilot_3",
            "expanded_6",
            "pilot_3",
            b_model,
            pilot_segment,
            b_train_count,
        )
        c_pilot["promotion_candidate"] = _promotion_candidate(a, c_pilot)
        rows.append(c_pilot)
        rows.append(
            _evaluate_existing_model_row(
                "C",
                "expanded_only",
                "expanded_6",
                "expanded_6",
                b_model,
                expanded_only,
                b_train_count,
            )
        )
        for prefix, segment in sorted(b_test.groupby("station_prefix"), key=lambda item: str(item[0])):
            rows.append(
                _evaluate_existing_model_row(
                    "C",
                    f"station:{prefix}",
                    "expanded_6",
                    str(prefix),
                    b_model,
                    segment.copy(),
                    b_train_count,
                )
            )
    return rows


def review_station_mapping(
    frame: pd.DataFrame,
    mapping_rows: list[dict[str, str]],
    runtime_prefix_counts: dict[str, int] | None = None,
) -> list[dict[str, str]]:
    enriched = _enrich_scope(frame, mapping_rows)
    runtime_prefix_counts = runtime_prefix_counts or {}
    mapping_by_prefix = {
        str(row.get("station_prefix") or "").strip().upper(): row
        for row in mapping_rows
        if str(row.get("station_prefix") or "").strip()
    }
    prefixes = set(mapping_by_prefix)
    prefixes.update(prefix for prefix in enriched.get("station_prefix", []) if prefix)
    prefixes.update(prefix for prefix in runtime_prefix_counts if prefix)

    rows = []
    for prefix in sorted(prefixes):
        mapping = mapping_by_prefix.get(
            prefix,
            {
                "station_prefix": prefix,
                "district": "unknown",
                "scope": "unknown",
                "status": "pending",
                "notes": "Discovered in local data but missing from station mapping.",
            },
        )
        segment = enriched[enriched["station_prefix"] == prefix].copy()
        target = pd.to_numeric(segment.get("target_etr_minutes"), errors="coerce") if not segment.empty else pd.Series(dtype=float)
        target = target.dropna()
        status = str(mapping.get("status") or "").strip().lower()
        scope = str(mapping.get("scope") or "").strip().lower()
        training_rows = int(len(segment))
        runtime_events = int(runtime_prefix_counts.get(prefix, 0))
        recommendation = _station_review_recommendation(status, scope, training_rows, runtime_events)
        rows.append(
            {
                "station_prefix": prefix,
                "district": mapping.get("district") or "unknown",
                "scope": scope or "unknown",
                "status": status or "pending",
                "training_rows": str(training_rows),
                "runtime_events": str(runtime_events),
                "target_median_minutes": _fmt(target.median()) if not target.empty else "",
                "target_p90_minutes": _fmt(target.quantile(0.9)) if not target.empty else "",
                "top_feeders": _top_counts_text(segment, "Feeder"),
                "top_site_detail": _top_counts_text(segment, "SiteDetail"),
                "top_op_device_site_id": _top_counts_text(segment, "OpDeviceSiteID"),
                "top_affected_site_id": _top_counts_text(segment, "AffectedSiteID"),
                "recommendation": recommendation,
                "review_note": _station_review_note(recommendation, mapping, training_rows, runtime_events),
            }
        )
    return rows


def _time_holdout_row(
    model_variant: str,
    evaluation_segment: str,
    train_scope: str,
    frame: pd.DataFrame,
    eval_scope: str,
) -> dict[str, str]:
    model, test, train_count = _fit_holdout_model(frame)
    if model is None or test is None:
        return _insufficient_row(
            model_variant,
            evaluation_segment,
            train_scope,
            eval_scope,
            int(len(frame)),
            "requires at least 30 rows with event_start and target_etr_minutes",
        )
    return _evaluate_existing_model_row(model_variant, evaluation_segment, train_scope, eval_scope, model, test, train_count)


def _fit_holdout_model(frame: pd.DataFrame) -> tuple[dict[str, Any] | None, pd.DataFrame | None, int]:
    usable = frame.dropna(subset=["event_start", "target_etr_minutes"]).sort_values("event_start")
    if len(usable) < 30:
        return None, None, 0
    split = max(1, int(len(usable) * 0.8))
    train = usable.iloc[:split].copy()
    test = usable.iloc[split:].copy()
    return fit_quantile_baseline(train), test, int(len(train))


def _evaluate_existing_model_row(
    model_variant: str,
    evaluation_segment: str,
    train_scope: str,
    eval_scope: str,
    model: dict[str, Any],
    test: pd.DataFrame,
    rows_train: int,
) -> dict[str, str]:
    if test.empty:
        return _insufficient_row(model_variant, evaluation_segment, train_scope, eval_scope, rows_train, "no rows in evaluation segment")
    preds = []
    for _, row in test.iterrows():
        preds.append(_row_prediction(model, str(row.get("Feeder")), str(row.get("device_type_model"))))
    pred_df = pd.DataFrame(preds)
    actual = pd.to_numeric(test["target_etr_minutes"], errors="coerce").reset_index(drop=True)
    mae = (pred_df["q50"] - actual).abs().mean()
    coverage = ((actual >= pred_df["q10"]) & (actual <= pred_df["q90"])).mean()
    status = "gate_pass" if mae <= 16 and 0.75 <= coverage <= 0.90 else "gate_fail"
    return {
        "model_variant": model_variant,
        "evaluation_segment": evaluation_segment,
        "train_scope": train_scope,
        "eval_scope": eval_scope,
        "rows_train": str(rows_train),
        "rows_test": str(int(len(test))),
        "q50_mae_minutes": _fmt(mae),
        "q10_q90_coverage": _fmt(coverage, digits=3),
        "status": status,
        "promotion_candidate": "NO",
        "notes": "gate q50 MAE <= 16 and q10-q90 coverage 0.75-0.90",
    }


def _promotion_candidate(baseline: dict[str, str], candidate: dict[str, str]) -> str:
    try:
        baseline_mae = float(baseline.get("q50_mae_minutes") or "nan")
        candidate_mae = float(candidate.get("q50_mae_minutes") or "nan")
        candidate_coverage = float(candidate.get("q10_q90_coverage") or "nan")
    except ValueError:
        return "NO"
    if candidate_mae <= baseline_mae and 0.75 <= candidate_coverage <= 0.90:
        return "YES"
    return "NO"


def _insufficient_row(
    model_variant: str,
    evaluation_segment: str,
    train_scope: str,
    eval_scope: str,
    rows: int,
    notes: str,
) -> dict[str, str]:
    return {
        "model_variant": model_variant,
        "evaluation_segment": evaluation_segment,
        "train_scope": train_scope,
        "eval_scope": eval_scope,
        "rows_train": str(rows),
        "rows_test": "0",
        "q50_mae_minutes": "",
        "q10_q90_coverage": "",
        "status": "insufficient_data",
        "promotion_candidate": "NO",
        "notes": notes,
    }


def _enrich_scope(frame: pd.DataFrame, mapping_rows: list[dict[str, str]]) -> pd.DataFrame:
    mapping = {
        str(row.get("station_prefix") or "").strip().upper(): row
        for row in mapping_rows
        if str(row.get("station_prefix") or "").strip()
    }
    result = frame.copy()
    result["station_prefix"] = result.get("Feeder", "").apply(_prefix_from_feeder)
    result["scope"] = result["station_prefix"].map(lambda prefix: mapping.get(prefix, {}).get("scope", "unknown"))
    result["mapping_status"] = result["station_prefix"].map(lambda prefix: mapping.get(prefix, {}).get("status", "pending"))
    result["district_mapped"] = result["station_prefix"].map(lambda prefix: mapping.get(prefix, {}).get("district", "unknown"))
    return result


def _scope_filtered_frame(frame: pd.DataFrame, mapping_rows: list[dict[str, str]], train_scope: str) -> pd.DataFrame:
    enriched = _enrich_scope(frame, mapping_rows)
    included = _included_scopes(train_scope)
    return enriched[
        (enriched["mapping_status"] == "approved")
        & (enriched["scope"].isin(included))
    ].copy()


def _included_scopes(train_scope: str) -> list[str]:
    scope = str(train_scope or "").strip().lower()
    if scope == "pilot_3":
        return ["pilot_3"]
    if scope == "expanded_6":
        return ["pilot_3", "expanded_6"]
    raise ValueError("train_scope must be 'pilot_3' or 'expanded_6'")


def _render_markdown(rows: list[dict[str, str]], mapping_rows: list[dict[str, str]], *, mapping_ready: bool) -> str:
    candidate = next((row for row in rows if row.get("promotion_candidate") == "YES"), None)
    mapping_counts = Counter(row.get("status") or "<blank>" for row in mapping_rows)
    lines = [
        "# AIS ETR Model Scope Calibration",
        "",
        "This report compares pilot-only training with expanded-six-area training without overwriting the runtime model artifact.",
        "",
        "## Mapping Readiness",
        "",
        "| Mapping status | Station prefixes |",
        "| --- | ---: |",
    ]
    for status, count in sorted(mapping_counts.items()):
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
            "",
            "## Model Comparison",
            "",
            "| Variant | Segment | Train scope | Rows train | Rows test | q50 MAE | q10-q90 coverage | Status | Promote? |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['model_variant']} | {row['evaluation_segment']} | {row['train_scope']} | "
            f"{row['rows_train']} | {row['rows_test']} | {row['q50_mae_minutes']} | "
            f"{row['q10_q90_coverage']} | {row['status']} | {row['promotion_candidate']} |"
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            _scope_recommendation_text(candidate, mapping_ready),
            "",
            "## Safety Notes",
            "",
            "- This report does not change `runtime/model_quantiles.json`.",
            "- Unknown or pending station prefixes are excluded from model comparison and must be reviewed before promotion.",
            "- Production/customer-facing scope remains the original three pilot districts.",
        ]
    )
    return "\n".join(lines)


def _render_challenger_markdown(summary: dict[str, Any], output_model: Path) -> str:
    metrics = summary.get("metrics") or {}
    gate = metrics.get("gate") or {"q50_mae_max": 16, "coverage_min": 0.75, "coverage_max": 0.90}
    lines = [
        "# AIS ETR Shadow Challenger Model",
        "",
        "This artifact is trained for offline shadow comparison only. It does not overwrite `runtime/model_quantiles.json`.",
        "",
        "## Artifact",
        "",
        f"- Model path: `{output_model}`",
        f"- Model version: `{summary.get('model_version')}`",
        f"- Train scope: `{summary.get('train_scope')}`",
        f"- Included scopes: {', '.join(summary.get('included_scopes') or [])}",
        f"- Training rows: {summary.get('rows_train_full')}",
        "",
        "## Holdout Metrics",
        "",
        "| Metric | Value | Gate |",
        "| --- | ---: | --- |",
        f"| q50 MAE minutes | {metrics.get('q50_mae_minutes', '')} | <= {gate.get('q50_mae_max', 16)} |",
        f"| q10-q90 coverage | {metrics.get('q10_q90_coverage', '')} | {gate.get('coverage_min', 0.75)}-{gate.get('coverage_max', 0.90)} |",
        f"| Status | {metrics.get('status', 'unknown')} | gate_pass required for production |",
        "",
        "## Scope Counts",
        "",
        "| Scope | Rows |",
        "| --- | ---: |",
    ]
    for scope, count in (summary.get("scope_counts") or {}).items():
        lines.append(f"| {scope} | {count} |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "This challenger passes the production model gate on historical holdout, but still needs live shadow evaluation before customer sends."
                if summary.get("production_ready")
                else "This challenger is for shadow comparison only; it is not production-ready until it passes q50 MAE <= 16 minutes and q10-q90 coverage 75-90% on pilot evaluation."
            ),
            "",
            "## Safety Notes",
            "",
            "- No production notification behavior changes.",
            "- No PEANO list, raw Webex text, room identifiers, credential values, or customer registration names are included.",
        ]
    )
    return "\n".join(lines)


def _scope_recommendation_text(candidate: dict[str, str] | None, mapping_ready: bool) -> str:
    if not candidate:
        return "Do not promote expanded-six-area training yet. Keep deployment/evaluation gate on the original three pilot districts until pilot metrics improve."
    if not mapping_ready:
        return "Expanded training metrics have a possible shadow challenger, but promotion is blocked until pending or unknown station mappings are reviewed."
    if candidate.get("status") == "gate_pass":
        return "Expanded training is a promotion candidate because it does not degrade pilot q50 MAE and passes the production model gate."
    return (
        "Expanded training is a shadow challenger candidate because pilot q50 MAE improves versus pilot-only training and q10-q90 coverage is in range. "
        "It is not production-ready yet because the pilot q50 MAE still fails the <=16 minute gate."
    )


def _mapping_ready(mapping_rows: list[dict[str, str]]) -> bool:
    for row in mapping_rows:
        status = str(row.get("status") or "").strip().lower()
        scope = str(row.get("scope") or "").strip().lower()
        if status != "approved" or scope == "unknown":
            return False
    return True


def _runtime_station_prefixes(db_path: str | Path) -> set[str]:
    return set(_runtime_station_prefix_counts(db_path))


def _runtime_station_prefix_counts(db_path: str | Path) -> dict[str, int]:
    path = Path(db_path)
    if not path.exists():
        return {}
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute("SELECT feeder FROM outage_events WHERE feeder IS NOT NULL").fetchall()
        counts: Counter[str] = Counter()
        for row in rows:
            prefix = _prefix_from_feeder(row[0])
            if prefix:
                counts[prefix] += 1
        return dict(sorted(counts.items()))
    finally:
        conn.close()


def _runtime_events(db_path: str | Path) -> list[OutageEvent]:
    path = Path(db_path)
    if not path.exists():
        return []
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT event_id, webex_message_id, event_time, district, site, device_type, device_id, feeder, parsed_json
            FROM outage_events
            ORDER BY event_time, event_id
            """
        ).fetchall()
    finally:
        conn.close()
    events = []
    for row in rows:
        parsed = _safe_json(row["parsed_json"])
        device = parsed.get("outage_device") if isinstance(parsed.get("outage_device"), dict) else {}
        parsed_fields = parsed.get("parsed_fields") if isinstance(parsed.get("parsed_fields"), dict) else {}
        events.append(
            OutageEvent(
                event_id=str(row["event_id"]),
                source=str(parsed.get("source") or "webex"),
                webex_message_id=row["webex_message_id"],
                room_id=None,
                raw_text="",
                outage_device=OutageDevice(
                    device_type=str(device.get("device_type") or row["device_type"] or "Unknown"),
                    device_id=device.get("device_id") or row["device_id"],
                    feeder=device.get("feeder") or row["feeder"],
                ),
                event_time=row["event_time"],
                district=row["district"],
                site=row["site"],
                parsed_fields=parsed_fields,
            )
        )
    return events


def _safe_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _redacted_ref(value: str | None) -> str:
    if not value:
        return ""
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"msg-{digest}"


def _load_simple_truth_mapping(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not path or not Path(path).exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            message_id = str(row.get("webex_message_id") or "").strip()
            if not message_id:
                continue
            actual = _to_float(row.get("actual_restoration_minutes"))
            if actual is None:
                continue
            rows[message_id] = {
                "actual_restoration_minutes": actual,
                "truth_source": str(row.get("truth_source") or "").strip(),
                "truth_quality": str(row.get("truth_quality") or "").strip(),
            }
    return rows


def _prefix_from_feeder(value: Any) -> str:
    feeder = normalize_feeder(value)
    if not feeder:
        return ""
    return str(feeder)[:3].upper()


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _shadow_model_comparison_summary(
    rows: list[dict[str, str]],
    current_model: dict[str, Any],
    challenger_model: dict[str, Any],
) -> dict[str, Any]:
    total = len(rows)
    truth_rows = [row for row in rows if str(row.get("actual_restoration_minutes") or "").strip()]
    current_errors = [_to_float(row.get("current_absolute_error")) for row in truth_rows]
    challenger_errors = [_to_float(row.get("challenger_absolute_error")) for row in truth_rows]
    current_errors = [value for value in current_errors if value is not None]
    challenger_errors = [value for value in challenger_errors if value is not None]
    deltas = [_to_float(row.get("absolute_error_delta_challenger_minus_current")) for row in truth_rows]
    deltas = [value for value in deltas if value is not None]
    current_covered = _coverage_from_rows(truth_rows, "current_covered_q10_q90")
    challenger_covered = _coverage_from_rows(truth_rows, "challenger_covered_q10_q90")
    return {
        "events": total,
        "with_truth": len(truth_rows),
        "current_model_version": current_model.get("model_version", "unknown"),
        "challenger_model_version": challenger_model.get("model_version", "unknown"),
        "current_q50_mae_minutes": _round_or_none(_mean(current_errors)),
        "challenger_q50_mae_minutes": _round_or_none(_mean(challenger_errors)),
        "current_q10_q90_coverage": _round_or_none(current_covered, digits=3),
        "challenger_q10_q90_coverage": _round_or_none(challenger_covered, digits=3),
        "challenger_improved_events": sum(1 for value in deltas if value < 0),
        "challenger_worse_events": sum(1 for value in deltas if value > 0),
        "challenger_tied_events": sum(1 for value in deltas if value == 0),
        "production_gate": {
            "q50_mae_max": 16,
            "coverage_min": 0.75,
            "coverage_max": 0.90,
        },
    }


def _render_shadow_model_comparison_markdown(summary: dict[str, Any]) -> str:
    with_truth = int(summary.get("with_truth") or 0)
    challenger_mae = summary.get("challenger_q50_mae_minutes")
    challenger_coverage = summary.get("challenger_q10_q90_coverage")
    production_ready = (
        with_truth > 0
        and challenger_mae is not None
        and challenger_coverage is not None
        and float(challenger_mae) <= 16
        and 0.75 <= float(challenger_coverage) <= 0.90
    )
    lines = [
        "# AIS ETR Shadow Model Comparison",
        "",
        "This report compares the current runtime model and the expanded-scope challenger against available shadow truth without changing runtime predictions or notifications.",
        "",
        "## Summary",
        "",
        f"- Events evaluated: {summary.get('events')}",
        f"- Events with truth: {summary.get('with_truth')}",
        f"- Current model: `{summary.get('current_model_version')}`",
        f"- Challenger model: `{summary.get('challenger_model_version')}`",
        "",
        "## Metrics With Truth",
        "",
        "| Model | q50 MAE minutes | q10-q90 coverage |",
        "| --- | ---: | ---: |",
        f"| Current | {_blank_none(summary.get('current_q50_mae_minutes'))} | {_blank_none(summary.get('current_q10_q90_coverage'))} |",
        f"| Challenger | {_blank_none(summary.get('challenger_q50_mae_minutes'))} | {_blank_none(summary.get('challenger_q10_q90_coverage'))} |",
        "",
        "## Error Movement",
        "",
        f"- Challenger improved events: {summary.get('challenger_improved_events')}",
        f"- Challenger worse events: {summary.get('challenger_worse_events')}",
        f"- Challenger tied events: {summary.get('challenger_tied_events')}",
        "",
        "## Recommendation",
        "",
        (
            "The challenger passes the production gate on available truth, but still needs human approval and a sufficient live shadow sample before production sends."
            if production_ready
            else "Keep the challenger in shadow only. Do not use it for production sends until q50 MAE <= 16 minutes and q10-q90 coverage is 75-90% on sufficient pilot truth."
        ),
        "",
        "## Safety Notes",
        "",
        "- This report does not overwrite `runtime/model_quantiles.json`.",
        "- This report does not insert rows into `predictions` or `notifications`.",
        "- No PEANO list, raw Webex text, room identifiers, credential values, or customer registration names are included.",
    ]
    if with_truth == 0:
        lines.insert(
            lines.index("## Recommendation"),
            "No truth rows are available, so this report cannot claim model accuracy.",
        )
        lines.insert(lines.index("## Recommendation"), "")
    return "\n".join(lines)


def _render_review_markdown(rows: list[dict[str, str]]) -> str:
    recommendation_counts = Counter(row.get("recommendation") or "<blank>" for row in rows)
    lines = [
        "# AIS ETR Station Mapping Review",
        "",
        "This review summarizes local evidence for station-prefix scope mapping before changing the model training pool.",
        "",
        "## Recommendation Summary",
        "",
        "| Recommendation | Station prefixes |",
        "| --- | ---: |",
    ]
    for recommendation, count in sorted(recommendation_counts.items()):
        lines.append(f"| {recommendation} | {count} |")
    lines.extend(
        [
            "",
            "## Prefix Evidence",
            "",
            "| Prefix | Scope | Status | Training rows | Runtime events | Top feeders | Recommendation |",
            "| --- | --- | --- | ---: | ---: | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['station_prefix']} | {row['scope']} | {row['status']} | "
            f"{row['training_rows']} | {row['runtime_events']} | {row['top_feeders']} | "
            f"{row['recommendation']} |"
        )

    review_rows = [row for row in rows if row.get("recommendation") == "owner_review_required"]
    if review_rows:
        lines.extend(["", "## Owner Review Required", ""])
        for row in review_rows:
            lines.append(f"### {row['station_prefix']}")
            lines.append("")
            lines.append(f"- Current mapping: `{row['scope']}` / `{row['status']}`")
            lines.append(f"- Training rows: {row['training_rows']}; runtime events: {row['runtime_events']}")
            if row.get("top_site_detail"):
                lines.append(f"- Top site detail values: {row['top_site_detail']}")
            if row.get("top_op_device_site_id"):
                lines.append(f"- Top operating site IDs: {row['top_op_device_site_id']}")
            lines.append(f"- Action: {row['review_note']}")
            lines.append("")

    lines.extend(
        [
            "## Safety Notes",
            "",
            "- This report does not approve or change any station mapping.",
            "- Pending or unknown prefixes remain excluded from scope calibration until reviewed.",
            "- Credential values, Webex raw text, room identifiers, PEANO lists, and customer registration names are not included.",
        ]
    )
    return "\n".join(lines)


def _station_review_recommendation(status: str, scope: str, training_rows: int, runtime_events: int) -> str:
    if status != "approved" or scope == "unknown":
        return "owner_review_required"
    if training_rows == 0 and runtime_events == 0:
        return "approved_no_current_rows"
    return "approved_for_scope_calibration"


def _station_review_note(
    recommendation: str,
    mapping: dict[str, str],
    training_rows: int,
    runtime_events: int,
) -> str:
    if recommendation == "owner_review_required":
        return "Confirm station prefix, district, and pilot/expanded scope with the topology or operations owner before using it."
    if recommendation == "approved_no_current_rows":
        return "Mapping is approved, but no local training or runtime rows were found in this batch."
    notes = str(mapping.get("notes") or "").strip()
    if notes:
        return notes
    return f"Approved mapping has {training_rows} training rows and {runtime_events} runtime events available for calibration."


def _top_counts_text(frame: pd.DataFrame, column: str, *, max_items: int = 5) -> str:
    if frame.empty or column not in frame.columns:
        return ""
    values: Counter[str] = Counter()
    for value in frame[column].tolist():
        cleaned = _clean_count_value(value)
        if cleaned:
            values[cleaned] += 1
    return "; ".join(f"{key}={count}" for key, count in values.most_common(max_items))


def _clean_count_value(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "<na>"} or text == "-":
        return ""
    return text


def _covered_text(actual: float | None, q10: float, q90: float) -> str:
    if actual is None:
        return ""
    return "TRUE" if float(q10) <= actual <= float(q90) else "FALSE"


def _coverage_from_rows(rows: list[dict[str, str]], column: str) -> float | None:
    values = [str(row.get(column) or "").strip().upper() for row in rows]
    values = [value for value in values if value in {"TRUE", "FALSE"}]
    if not values:
        return None
    return sum(1 for value in values if value == "TRUE") / len(values)


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


def _to_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any, *, digits: int = 2) -> str:
    try:
        return str(round(float(value), digits))
    except (TypeError, ValueError):
        return ""
