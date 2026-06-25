from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

from .evaluation import evaluate_sample_messages
from .matcher import ProtectionMatcher
from .model import EtrPredictor, _row_prediction, fit_quantile_baseline, load_training_frame
from .notifier import build_notification_payload
from .operations import validate_env
from .parser import parse_webex_message
from .registry import load_assets_from_upstream_result
from .schemas import utc_now_iso


SUMMARY_CSV = "shadow_readiness_summary.csv"
PARSER_MATCHING_CSV = "shadow_readiness_parser_matching_audit.csv"
MODEL_SEGMENTS_CSV = "shadow_readiness_model_error_segments.csv"
BACKLOG_CSV = "shadow_readiness_registry_backlog.csv"
PAYLOAD_EXAMPLE_JSON = "shadow_readiness_notification_payload.example.json"
MARKDOWN_REPORT = "shadow_readiness_report.md"


def build_shadow_readiness_pack(
    settings,
    samples_path: str | Path = "data/webex_shadow_samples.jsonl",
    output_dir: str | Path = "runtime",
    env_path: str | Path = ".env",
) -> dict[str, Any]:
    """Create a shadow readiness report without polling Webex or sending notifications."""
    out_dir = settings.resolve(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    generated_at = utc_now_iso()
    registry_path = settings.resolve(settings.registry_path)
    samples = settings.resolve(samples_path)
    model_path = settings.resolve(settings.model_path)
    db_path = settings.resolve(settings.db_path)

    assets = load_assets_from_upstream_result(registry_path) if registry_path.exists() else []
    registry = _registry_readiness(assets)
    runtime_counts = _runtime_counts(db_path)
    env = validate_env(settings, env_path)

    parser_eval = _safe_sample_eval(samples, settings.pilot_districts)
    sample_records = _read_sample_records(samples)
    predictor = EtrPredictor.load(model_path)
    audit_rows, match_counts, missing_fields, sample_shape, payload_example = _sample_parser_matching_audit(
        sample_records,
        settings.pilot_districts,
        assets,
        predictor,
        settings.notification_mode,
    )

    model_artifact = _model_artifact_summary(model_path)
    model_segments, holdout_summary = _model_error_segments(settings)
    etr_quality = _etr_quality(settings)

    blockers = _top_blockers(env, sample_shape, registry, model_artifact)
    summary_rows = _summary_rows(
        env=env,
        runtime_counts=runtime_counts,
        parser_eval=parser_eval,
        sample_shape=sample_shape,
        registry=registry,
        match_counts=match_counts,
        model_artifact=model_artifact,
        holdout_summary=holdout_summary,
        etr_quality=etr_quality,
        blockers=blockers,
    )

    summary_csv = out_dir / SUMMARY_CSV
    parser_matching_csv = out_dir / PARSER_MATCHING_CSV
    model_segments_csv = out_dir / MODEL_SEGMENTS_CSV
    backlog_csv = out_dir / BACKLOG_CSV
    payload_json = out_dir / PAYLOAD_EXAMPLE_JSON
    markdown = out_dir / MARKDOWN_REPORT

    _write_csv(summary_csv, summary_rows)
    _write_csv(parser_matching_csv, audit_rows)
    _write_csv(model_segments_csv, model_segments)
    _write_csv(backlog_csv, _backlog_rows(registry))
    payload_json.write_text(
        json.dumps(payload_example or {}, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8-sig",
    )
    markdown.write_text(
        _render_markdown(
            generated_at=generated_at,
            env=env,
            runtime_counts=runtime_counts,
            parser_eval=parser_eval,
            sample_shape=sample_shape,
            registry=registry,
            match_counts=match_counts,
            missing_fields=missing_fields,
            model_artifact=model_artifact,
            holdout_summary=holdout_summary,
            model_segments=model_segments,
            etr_quality=etr_quality,
            blockers=blockers,
            outputs={
                "summary_csv": summary_csv.name,
                "parser_matching_csv": parser_matching_csv.name,
                "model_segments_csv": model_segments_csv.name,
                "backlog_csv": backlog_csv.name,
                "payload_example_json": payload_json.name,
            },
        ),
        encoding="utf-8-sig",
    )

    return {
        "status": "created",
        "generated_at": generated_at,
        "report_markdown": str(markdown),
        "summary_csv": str(summary_csv),
        "parser_matching_csv": str(parser_matching_csv),
        "model_segments_csv": str(model_segments_csv),
        "backlog_csv": str(backlog_csv),
        "payload_example_json": str(payload_json),
        "top_blockers": blockers[:3],
        "parser_success_rate": parser_eval.get("parser_success_rate"),
        "match_counts": match_counts,
        "registry": registry,
        "model": model_artifact,
    }


def _safe_sample_eval(samples: Path, districts: tuple[str, ...]) -> dict[str, Any]:
    if not samples.exists():
        return {
            "source": str(samples),
            "total": 0,
            "parsed": 0,
            "passed": 0,
            "failed": 0,
            "parser_success_rate": None,
            "expectation_pass_rate": None,
            "failures": [{"reason": "sample_file_missing"}],
        }
    return evaluate_sample_messages(samples, districts)


def _read_sample_records(path: Path) -> list[tuple[int, dict[str, Any]]]:
    if not path.exists():
        return []
    records: list[tuple[int, dict[str, Any]]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        records.append((line_no, json.loads(line)))
    return records


def _sample_parser_matching_audit(
    records: list[tuple[int, dict[str, Any]]],
    districts: tuple[str, ...],
    assets,
    predictor: EtrPredictor,
    notification_mode: str,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int], dict[str, Any], dict[str, Any] | None]:
    matcher = ProtectionMatcher(assets)
    rows: list[dict[str, Any]] = []
    match_counts: Counter[str] = Counter()
    missing_fields: Counter[str] = Counter()
    payload_example = None
    synthetic = 0

    for line_no, item in records:
        expected_ignored = bool((item.get("expected") or {}).get("ignored"))
        message_id = str(item.get("id") or "")
        if message_id.startswith("sample-") or item.get("roomId") == "sample-room":
            synthetic += 1

        event = parse_webex_message(item, districts=districts)
        parsed = event is not None
        row: dict[str, Any] = {
            "line": line_no,
            "message_id": message_id,
            "expected_ignored": expected_ignored,
            "parsed": parsed,
            "device_type": None,
            "device_id_present": False,
            "feeder": None,
            "district_present": False,
            "event_time_present": False,
            "event_number_present": False,
            "missing_fields": "",
            "match_level": "ignored" if expected_ignored else "not_parsed",
            "match_confidence": 0.0,
            "affected_count": 0,
            "risk_level": None,
            "model_version": predictor.model.get("model_version", "default-untrained"),
        }

        if event is None:
            if not expected_ignored:
                missing_fields["not_parsed"] += 1
            rows.append(row)
            continue

        missing = []
        if not event.outage_device.device_id:
            missing.append("device_id")
            missing_fields["device_id"] += 1
        if not event.outage_device.feeder:
            missing.append("feeder")
            missing_fields["feeder"] += 1
        if not event.district:
            missing.append("district")
            missing_fields["district"] += 1
        if not event.event_time:
            missing.append("event_time")
            missing_fields["event_time"] += 1
        if not event.parsed_fields.get("event_number"):
            missing.append("event_number")
            missing_fields["event_number"] += 1

        match_result = matcher.match(event)
        prediction = predictor.predict(event, match_result)
        level = match_result.match_level or "no_match"
        match_counts[level] += 1

        row.update(
            {
                "device_type": event.outage_device.device_type,
                "device_id_present": bool(event.outage_device.device_id),
                "feeder": event.outage_device.feeder,
                "district_present": bool(event.district),
                "event_time_present": bool(event.event_time),
                "event_number_present": bool(event.parsed_fields.get("event_number")),
                "missing_fields": ",".join(missing),
                "match_level": level,
                "match_confidence": round(float(match_result.match_confidence), 3),
                "affected_count": len(match_result.matches),
                "risk_level": prediction.risk_level,
                "model_version": prediction.model_version,
            }
        )
        rows.append(row)

        if payload_example is None and match_result.matches:
            payload = build_notification_payload(event, match_result, prediction, mode=notification_mode)
            payload_example = _redact_payload(payload)

    sample_shape = {
        "total_samples": len(records),
        "synthetic_samples": synthetic,
        "real_like_samples": max(0, len(records) - synthetic),
        "needs_real_webex_samples": max(0, len(records) - synthetic) < 20,
    }
    return rows, dict(match_counts), dict(missing_fields), sample_shape, payload_example


def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = json.loads(json.dumps(payload, ensure_ascii=False))
    customers = redacted.get("affected_customers") or []
    total = len(customers)
    for customer in customers[:3]:
        if "peano" in customer:
            customer["peano"] = "REDACTED"
    redacted["affected_customers"] = customers[:3]
    redacted["affected_customer_count"] = total
    redacted["redaction_note"] = "Sample only; PEANO values and room identifiers are redacted. No payload was sent."
    source = redacted.get("source") or {}
    if source.get("room_id"):
        source["room_id"] = "REDACTED"
    redacted["source"] = source
    return redacted


def _registry_readiness(assets) -> dict[str, Any]:
    total = len(assets)
    eligible_assets = [asset for asset in assets if asset.confidence_eligible]
    no_meter = [asset for asset in assets if asset.trace_status == "NO_METER" or not asset.confidence_eligible]
    return {
        "total_assets": total,
        "confidence_eligible": len(eligible_assets),
        "no_meter_backlog": len(no_meter),
        "with_feeder": sum(1 for asset in assets if _has_mapping(asset.feeder)),
        "with_transformer": sum(1 for asset in assets if _has_mapping(asset.transformer_id, asset.transformer_peano)),
        "with_recloser": sum(1 for asset in assets if _has_mapping(*asset.recloser_ids)),
        "with_switch": sum(1 for asset in assets if _has_mapping(*asset.switch_ids)),
        "with_cb": sum(1 for asset in assets if _has_mapping(*asset.cb_ids)),
        "eligible_with_feeder": sum(1 for asset in eligible_assets if _has_mapping(asset.feeder)),
        "eligible_with_transformer": sum(
            1 for asset in eligible_assets if _has_mapping(asset.transformer_id, asset.transformer_peano)
        ),
        "eligible_with_recloser": sum(1 for asset in eligible_assets if _has_mapping(*asset.recloser_ids)),
        "eligible_with_switch": sum(1 for asset in eligible_assets if _has_mapping(*asset.switch_ids)),
        "eligible_with_cb": sum(1 for asset in eligible_assets if _has_mapping(*asset.cb_ids)),
    }


def _has_mapping(*values: Any) -> bool:
    missing_tokens = {"", "NO_METER", "NONE", "NULL", "NAN", "-"}
    return any(str(value).strip().upper() not in missing_tokens for value in values if value is not None)


def _runtime_counts(db_path: Path) -> dict[str, int | None]:
    tables = (
        "webex_messages",
        "outage_events",
        "customer_assets",
        "predictions",
        "notifications",
        "model_runs",
    )
    if not db_path.exists():
        return {table: None for table in tables}
    uri = "file:" + str(db_path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        counts = {}
        for table in tables:
            try:
                counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.OperationalError:
                counts[table] = None
        return counts
    finally:
        conn.close()


def _model_artifact_summary(model_path: Path) -> dict[str, Any]:
    if not model_path.exists():
        return {
            "model_version": "missing",
            "estimator": None,
            "status": "missing_model_artifact",
            "q50_mae_minutes": None,
            "q10_q90_coverage": None,
            "gate": {"q50_mae_max": 16, "coverage_min": 0.75, "coverage_max": 0.90},
        }
    model = json.loads(model_path.read_text(encoding="utf-8-sig"))
    metrics = model.get("metrics") or {}
    gate = metrics.get("gate") or {"q50_mae_max": 16, "coverage_min": 0.75, "coverage_max": 0.90}
    return {
        "model_version": model.get("model_version"),
        "estimator": model.get("estimator"),
        "status": metrics.get("status", "unknown"),
        "q50_mae_minutes": metrics.get("q50_mae_minutes"),
        "q10_q90_coverage": metrics.get("q10_q90_coverage"),
        "rows_train": metrics.get("rows_train"),
        "rows_test": metrics.get("rows_test"),
        "gate": gate,
    }


def _model_error_segments(settings, min_rows: int = 10) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        frame = load_training_frame(
            settings.resolve(settings.event_file),
            [settings.resolve(path) for path in settings.etr_files],
            settings.resolve(settings.distance_file),
        )
    except Exception as exc:
        return [], {"status": "unavailable", "reason": str(exc)[:300]}

    frame = frame.dropna(subset=["event_start", "target_etr_minutes"]).sort_values("event_start")
    if len(frame) < 30:
        return [], {"status": "insufficient_data", "rows": int(len(frame))}

    split = max(1, int(len(frame) * 0.8))
    train = frame.iloc[:split]
    test = frame.iloc[split:].copy()
    model = fit_quantile_baseline(train)
    preds = pd.DataFrame(
        [_row_prediction(model, str(row.get("Feeder")), str(row.get("device_type_model"))) for _, row in test.iterrows()]
    )
    for column in ("q10", "q50", "q90"):
        test[f"pred_{column}"] = pd.to_numeric(preds[column].reset_index(drop=True), errors="coerce").values
    actual = pd.to_numeric(test["target_etr_minutes"], errors="coerce")
    test["absolute_error_minutes"] = (test["pred_q50"] - actual).abs()
    test["covered_q10_q90"] = (actual >= test["pred_q10"]) & (actual <= test["pred_q90"])
    test["duration_band"] = pd.cut(
        actual,
        bins=[-0.01, 5, 30, 60, 120, 1440],
        labels=["0-5", "6-30", "31-60", "61-120", "121-1440"],
    ).astype(str)

    office_col = next(
        (column for column in ("อำเภอ", "สำนักงานการไฟฟ้า", "เขต", "AffectedAreaID") if column in test.columns),
        None,
    )
    rows: list[dict[str, Any]] = []
    rows.extend(_summarize_segment(test, "Feeder", "feeder", min_rows))
    rows.extend(_summarize_segment(test, "device_type_model", "device_type", min_rows))
    rows.extend(_summarize_segment(test, "duration_band", "duration_band", min_rows))
    if office_col:
        rows.extend(_summarize_segment(test, office_col, "office_or_area", min_rows))

    rows.sort(key=lambda row: (row["segment_type"], -row["rows"], -row["q50_mae_minutes"]))
    return rows, {
        "status": "ok",
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "q50_mae_minutes": round(float(test["absolute_error_minutes"].mean()), 2),
        "q10_q90_coverage": round(float(test["covered_q10_q90"].mean()), 3),
    }


def _summarize_segment(df: pd.DataFrame, column: str, segment_type: str, min_rows: int) -> list[dict[str, Any]]:
    rows = []
    scoped = df.copy()
    scoped[column] = scoped[column].fillna("<missing>").astype(str)
    for segment, group in scoped.groupby(column, dropna=False):
        if len(group) < min_rows:
            continue
        rows.append(
            {
                "segment_type": segment_type,
                "segment": segment,
                "rows": int(len(group)),
                "q50_mae_minutes": round(float(group["absolute_error_minutes"].mean()), 2),
                "q10_q90_coverage": round(float(group["covered_q10_q90"].mean()), 3),
                "actual_median_minutes": round(float(group["target_etr_minutes"].median()), 2),
                "predicted_median_minutes": round(float(group["pred_q50"].median()), 2),
            }
        )
    return rows


def _etr_quality(settings) -> dict[str, Any]:
    frames = []
    for path in settings.etr_files:
        source = settings.resolve(path)
        if not source.exists():
            continue
        df = pd.read_excel(source, header=2)
        df["source_file"] = source.name
        frames.append(df)
    if not frames:
        return {"status": "missing_etr_files", "rows": 0}

    df = pd.concat(frames, ignore_index=True)
    start = pd.to_datetime(df.get("เริ่มเหตุการณ์"), errors="coerce")
    restore = pd.to_datetime(df.get("จ่ายไฟกลับคืนครั้งแรก"), errors="coerce")
    duration = (restore - start).dt.total_seconds() / 60
    valid = duration.dropna()
    quality: dict[str, Any] = {
        "status": "ok",
        "rows": int(len(df)),
        "missing_start": int(start.isna().sum()),
        "missing_restore": int(restore.isna().sum()),
        "negative_duration": int((duration < 0).sum()),
        "zero_duration": int((duration == 0).sum()),
        "five_minutes_or_less": int(((duration >= 0) & (duration <= 5)).sum()),
        "over_24h": int((duration > 24 * 60).sum()),
        "median_minutes": round(float(valid.median()), 2) if not valid.empty else None,
        "p75_minutes": round(float(valid.quantile(0.75)), 2) if not valid.empty else None,
        "p95_minutes": round(float(valid.quantile(0.95)), 2) if not valid.empty else None,
        "p99_minutes": round(float(valid.quantile(0.99)), 2) if not valid.empty else None,
        "max_minutes": round(float(valid.max()), 2) if not valid.empty else None,
    }
    etr_time = pd.to_datetime(df.get("เวลาของ ETR"), errors="coerce")
    horizon = ((etr_time - start).dt.total_seconds() / 60).round()
    top_horizons = horizon.dropna().astype(int).value_counts().head(5).to_dict()
    quality["top_etr_horizons_minutes"] = {str(key): int(value) for key, value in top_horizons.items()}
    return quality


def _top_blockers(
    env: dict[str, Any],
    sample_shape: dict[str, Any],
    registry: dict[str, Any],
    model: dict[str, Any],
) -> list[dict[str, str]]:
    blockers = []
    if env.get("missing") or sample_shape.get("needs_real_webex_samples"):
        if env.get("webex_auth_mode") == "oauth":
            next_action = "Run webex-auth, select WEBEX_ROOM_ID with webex-rooms, and collect 20-50 real Webex outage messages."
        else:
            next_action = "Add WEBEX_BOT_TOKEN/WEBEX_ROOM_ID and collect 20-50 real mentioned Webex outage messages."
        blockers.append(
            {
                "blocker": "Webex shadow intake is not production-like yet",
                "why_it_matters": "No real room polling can run, and parser coverage is still based on synthetic samples.",
                "next_action": next_action,
            }
        )
    if model.get("status") != "gate_pass":
        blockers.append(
            {
                "blocker": "Model gate has not passed",
                "why_it_matters": f"Current q50 MAE is {model.get('q50_mae_minutes')} minutes versus the <=16 minute target.",
                "next_action": "Use shadow truth and high-error segments to add better features before any real customer send.",
            }
        )
    if registry.get("no_meter_backlog", 0):
        blockers.append(
            {
                "blocker": "NO_METER backlog remains in the AIS registry",
                "why_it_matters": f"{registry.get('no_meter_backlog')} AIS assets cannot be used for confident impact matching.",
                "next_action": "Repair meter trace records and rerun build-registry before production promotion.",
            }
        )
    if not env.get("mock_webhook_configured"):
        blockers.append(
            {
                "blocker": "Mock webhook endpoint is not configured",
                "why_it_matters": "Shadow payloads would be stored as skipped/no-endpoint instead of exercising delivery behavior.",
                "next_action": "Set AIS_MOCK_WEBHOOK_URL to an internal mock endpoint for end-to-end delivery checks.",
            }
        )
    return blockers


def _summary_rows(**items: Any) -> list[dict[str, Any]]:
    env = items["env"]
    runtime = items["runtime_counts"]
    parser = items["parser_eval"]
    sample_shape = items["sample_shape"]
    registry = items["registry"]
    match_counts = items["match_counts"]
    model = items["model_artifact"]
    holdout = items["holdout_summary"]
    etr = items["etr_quality"]
    blockers = items["blockers"]

    rows = [
        _metric("runtime", "webex_messages", runtime.get("webex_messages"), "INFO", "", "Current runtime DB count."),
        _metric("runtime", "outage_events", runtime.get("outage_events"), "INFO", "", "Current runtime DB count."),
        _metric("runtime", "predictions", runtime.get("predictions"), "INFO", "", "Current runtime DB count."),
        _metric("runtime", "notifications", runtime.get("notifications"), "INFO", "", "Current runtime DB count."),
        _metric(
            "environment",
            "webex_credentials",
            "missing: " + ",".join(env.get("missing", [])) if env.get("missing") else "configured",
            "BLOCKER" if env.get("missing") else "PASS",
            "OAuth config, token file, and room ID configured"
            if env.get("webex_auth_mode") == "oauth"
            else "WEBEX_BOT_TOKEN and WEBEX_ROOM_ID configured",
            "Required for real Webex polling.",
        ),
        _metric(
            "environment",
            "notification_mode",
            env.get("notification_mode", "shadow"),
            "PASS" if env.get("notification_mode", "shadow") == "shadow" else "BLOCKER",
            "shadow",
            "Production send is intentionally blocked.",
        ),
        _metric("parser", "total_samples", parser.get("total"), "INFO", "20-50 real samples", "Current corpus size."),
        _metric(
            "parser",
            "parser_success_rate",
            parser.get("parser_success_rate"),
            "PASS" if (parser.get("parser_success_rate") or 0) >= 0.95 else "WARN",
            ">=0.95 on representative samples",
            "Current corpus is not yet a real Webex history sample.",
        ),
        _metric(
            "parser",
            "real_like_samples",
            sample_shape.get("real_like_samples"),
            "BLOCKER" if sample_shape.get("needs_real_webex_samples") else "PASS",
            ">=20",
            "Synthetic sample IDs do not prove real Webex wording coverage.",
        ),
        _metric("registry", "total_assets", registry.get("total_assets"), "INFO", "", "AIS asset registry rows after dedupe."),
        _metric(
            "registry",
            "confidence_eligible",
            registry.get("confidence_eligible"),
            "INFO",
            "",
            "Eligible for confident protection matching.",
        ),
        _metric(
            "registry",
            "no_meter_backlog",
            registry.get("no_meter_backlog"),
            "BLOCKER" if registry.get("no_meter_backlog") else "PASS",
            "0 before production promotion",
            "Excluded from confident notification.",
        ),
        _metric("matching", "cb", match_counts.get("cb", 0), "INFO", "", "Sample audit match level count."),
        _metric("matching", "recloser", match_counts.get("recloser", 0), "INFO", "", "Sample audit match level count."),
        _metric("matching", "switch", match_counts.get("switch", 0), "INFO", "", "Sample audit match level count."),
        _metric("matching", "transformer", match_counts.get("transformer", 0), "INFO", "", "Sample audit match level count."),
        _metric("matching", "feeder", match_counts.get("feeder", 0), "WARN", "", "Feeder fallback is low-confidence shadow-only."),
        _metric("matching", "no_match", match_counts.get("no_match", 0), "WARN", "minimize", "Sample audit no-match count."),
        _metric(
            "model",
            "q50_mae_minutes",
            model.get("q50_mae_minutes"),
            "PASS" if _as_float(model.get("q50_mae_minutes")) is not None and _as_float(model.get("q50_mae_minutes")) <= 16 else "BLOCKER",
            "<=16",
            f"Model status: {model.get('status')}",
        ),
        _metric(
            "model",
            "q10_q90_coverage",
            model.get("q10_q90_coverage"),
            "PASS"
            if _coverage_pass(model.get("q10_q90_coverage"), model.get("gate", {}))
            else "WARN",
            "0.75-0.90",
            "Coverage should be useful without becoming too wide.",
        ),
        _metric("model", "holdout_rows_test", holdout.get("rows_test"), "INFO", "", "Freshly recomputed from training frame."),
        _metric("etr_quality", "missing_restore", etr.get("missing_restore"), "WARN", "review", "Rows without first restoration time."),
        _metric("etr_quality", "negative_duration", etr.get("negative_duration"), "WARN", "0", "Likely data correction or timestamp issue."),
        _metric("etr_quality", "zero_duration", etr.get("zero_duration"), "WARN", "review", "May indicate short events or manual adjustment."),
    ]
    for rank, blocker in enumerate(blockers[:3], 1):
        rows.append(_metric("blocker", f"top_{rank}", blocker["blocker"], "BLOCKER", "", blocker["next_action"]))
    return rows


def _metric(category: str, metric: str, value: Any, status: str, target: str, note: str) -> dict[str, Any]:
    return {"category": category, "metric": metric, "value": value, "status": status, "target": target, "note": note}


def _coverage_pass(value: Any, gate: dict[str, Any]) -> bool:
    numeric = _as_float(value)
    if numeric is None:
        return False
    return float(gate.get("coverage_min", 0.75)) <= numeric <= float(gate.get("coverage_max", 0.90))


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _backlog_rows(registry: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    if registry.get("no_meter_backlog", 0):
        rows.append(
            {
                "priority": "P1",
                "issue": "NO_METER trace status",
                "rows": registry["no_meter_backlog"],
                "customer": "AIS",
                "notification_rule": "exclude from confident match",
                "repair_action": "Resolve meter trace to feeder/transformer/protection hierarchy, then rerun build-registry.",
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in rows for key in row.keys()})
    if not columns:
        columns = ["status"]
        rows = [{"status": "no_rows"}]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _render_markdown(
    *,
    generated_at: str,
    env: dict[str, Any],
    runtime_counts: dict[str, Any],
    parser_eval: dict[str, Any],
    sample_shape: dict[str, Any],
    registry: dict[str, Any],
    match_counts: dict[str, int],
    missing_fields: dict[str, int],
    model_artifact: dict[str, Any],
    holdout_summary: dict[str, Any],
    model_segments: list[dict[str, Any]],
    etr_quality: dict[str, Any],
    blockers: list[dict[str, str]],
    outputs: dict[str, str],
) -> str:
    top_segments = sorted(model_segments, key=lambda row: row.get("q50_mae_minutes") or 0, reverse=True)[:8]
    lines = [
        "# AIS ETR Shadow Readiness Report",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "## Executive Summary",
        "",
        "- **Shadow pilot is not ready for production send.** The pipeline remains correctly constrained to shadow mode, and runtime has no real Webex events, predictions, or notifications yet.",
        f"- **Parser baseline is strong but synthetic.** Current sample parser success is `{parser_eval.get('parser_success_rate')}`, from `{parser_eval.get('total')}` samples; real-like Webex sample count is `{sample_shape.get('real_like_samples')}`.",
        f"- **Registry is usable for traced assets only.** `{registry.get('confidence_eligible')}` of `{registry.get('total_assets')}` AIS assets are confidence-eligible; `{registry.get('no_meter_backlog')}` remain in the NO_METER repair backlog.",
        f"- **Model is still below the customer-send gate.** Current q50 MAE is `{model_artifact.get('q50_mae_minutes')}` minutes versus target `<=16`; q10-q90 coverage is `{model_artifact.get('q10_q90_coverage')}`.",
        "",
        "## Top 3 Production Blockers",
        "",
    ]
    if blockers:
        for idx, blocker in enumerate(blockers[:3], 1):
            lines.extend(
                [
                    f"{idx}. **{blocker['blocker']}**",
                    f"   - Why it matters: {blocker['why_it_matters']}",
                    f"   - Next action: {blocker['next_action']}",
                ]
            )
    else:
        lines.append("No blocking gaps detected in the available evidence.")

    lines.extend(
        [
            "",
            "## Runtime And Environment",
            "",
            _table(
                ["Metric", "Value"],
                [
                    ["Webex messages", runtime_counts.get("webex_messages")],
                    ["Outage events", runtime_counts.get("outage_events")],
                    ["Predictions", runtime_counts.get("predictions")],
                    ["Notifications", runtime_counts.get("notifications")],
                    ["Model runs", runtime_counts.get("model_runs")],
                    ["Webex auth mode", env.get("webex_auth_mode")],
                    ["Webex missing keys", ", ".join(env.get("missing", [])) or "none"],
                    ["Webex token file exists", (env.get("webex_token") or {}).get("exists")],
                    ["Notification mode", env.get("notification_mode", "shadow")],
                    ["Mock webhook configured", "yes" if env.get("mock_webhook_configured") else "no"],
                ],
            ),
            "",
            "## Webex Parser Readiness",
            "",
            _table(
                ["Metric", "Value"],
                [
                    ["Sample messages", parser_eval.get("total")],
                    ["Parsed messages", parser_eval.get("parsed")],
                    ["Parser success rate", parser_eval.get("parser_success_rate")],
                    ["Expectation pass rate", parser_eval.get("expectation_pass_rate")],
                    ["Synthetic samples", sample_shape.get("synthetic_samples")],
                    ["Real-like samples", sample_shape.get("real_like_samples")],
                    ["Needs real Webex samples", sample_shape.get("needs_real_webex_samples")],
                ],
            ),
            "",
            "Missing parsed fields across parsed sample messages:",
            "",
            _table(["Field", "Missing Count"], sorted(missing_fields.items())),
            "",
            "## AIS Registry Readiness",
            "",
            _table(
                ["Metric", "All Assets", "Confidence-Eligible Assets"],
                [
                    ["Total / eligible", registry.get("total_assets"), registry.get("confidence_eligible")],
                    ["With feeder", registry.get("with_feeder"), registry.get("eligible_with_feeder")],
                    ["With transformer", registry.get("with_transformer"), registry.get("eligible_with_transformer")],
                    ["With recloser", registry.get("with_recloser"), registry.get("eligible_with_recloser")],
                    ["With switch", registry.get("with_switch"), registry.get("eligible_with_switch")],
                    ["With CB", registry.get("with_cb"), registry.get("eligible_with_cb")],
                    ["NO_METER backlog", registry.get("no_meter_backlog"), "excluded"],
                ],
            ),
            "",
            "## Protection Matching Readiness",
            "",
            "Sample audit uses parsed Webex sample messages against the current AIS traced registry. It reports only counts and readiness fields; raw PEANO values are not included.",
            "",
            _table(["Match Level", "Sample Count"], sorted(match_counts.items())),
            "",
            "Feeder fallback remains low-confidence and shadow-only because it can over-match downstream customers.",
            "",
            "## Model Readiness",
            "",
            _table(
                ["Metric", "Value"],
                [
                    ["Model version", model_artifact.get("model_version")],
                    ["Estimator", model_artifact.get("estimator")],
                    ["Gate status", model_artifact.get("status")],
                    ["q50 MAE minutes", model_artifact.get("q50_mae_minutes")],
                    ["q10-q90 coverage", model_artifact.get("q10_q90_coverage")],
                    ["Fresh holdout rows", holdout_summary.get("rows_test")],
                    ["Fresh holdout q50 MAE", holdout_summary.get("q50_mae_minutes")],
                    ["Fresh holdout q10-q90 coverage", holdout_summary.get("q10_q90_coverage")],
                ],
            ),
            "",
            "Highest-error holdout segments, grouped by feeder, device type, duration band, and office/area where available:",
            "",
            _table(
                ["Segment Type", "Segment", "Rows", "q50 MAE", "Coverage", "Actual Median", "Predicted Median"],
                [
                    [
                        row.get("segment_type"),
                        row.get("segment"),
                        row.get("rows"),
                        row.get("q50_mae_minutes"),
                        row.get("q10_q90_coverage"),
                        row.get("actual_median_minutes"),
                        row.get("predicted_median_minutes"),
                    ]
                    for row in top_segments
                ],
            ),
            "",
            "## ETR Data Quality Caveats",
            "",
            _table(
                ["Metric", "Value"],
                [
                    ["Rows", etr_quality.get("rows")],
                    ["Missing start", etr_quality.get("missing_start")],
                    ["Missing first restoration", etr_quality.get("missing_restore")],
                    ["Negative duration", etr_quality.get("negative_duration")],
                    ["Zero duration", etr_quality.get("zero_duration")],
                    ["0-5 minute duration", etr_quality.get("five_minutes_or_less")],
                    [">24h duration", etr_quality.get("over_24h")],
                    ["Median restoration minutes", etr_quality.get("median_minutes")],
                    ["p95 restoration minutes", etr_quality.get("p95_minutes")],
                    ["Max restoration minutes", etr_quality.get("max_minutes")],
                    ["Top ETR horizons", json.dumps(etr_quality.get("top_etr_horizons_minutes", {}), ensure_ascii=False)],
                ],
            ),
            "",
            "Historical ETR horizon values are heavily rounded/default-like, so the model target should remain actual restoration minutes rather than the historical ETR timestamp.",
            "",
            "## Output Files",
            "",
            _table(["File", "Purpose"], [[name, purpose] for purpose, name in outputs.items()]),
            "",
            "## Readiness Decision",
            "",
            "Proceed with offline shadow evidence work and real Webex sample collection. Do not build the Demo UI or enable production AIS delivery until the Webex sample corpus, registry repair backlog, and model gate have improved.",
            "",
        ]
    )
    return "\n".join(lines)


def _table(headers: list[Any], rows: list[Any]) -> str:
    normalized_rows = [list(row) for row in rows]
    if not normalized_rows:
        normalized_rows = [["none" for _ in headers]]
    output = [
        "| " + " | ".join(str(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in normalized_rows:
        padded = row + [""] * (len(headers) - len(row))
        output.append("| " + " | ".join(_md_cell(value) for value in padded[: len(headers)]) + " |")
    return "\n".join(output)


def _md_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")
