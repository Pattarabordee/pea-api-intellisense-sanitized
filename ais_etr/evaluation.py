from __future__ import annotations

import csv
import json
from pathlib import Path
import sqlite3
from typing import Any

import pandas as pd

from .parser import parse_webex_message


TRUTH_MAPPING_COLUMNS = (
    "webex_message_id",
    "event_number",
    "actual_restoration_minutes",
    "truth_source",
    "truth_target",
    "truth_definition",
    "truth_quality",
    "truth_notes",
)
TRUTH_MAPPING_REQUIRED_COLUMNS = TRUTH_MAPPING_COLUMNS[:3]
CANONICAL_TRUTH_SOURCE = "ais_meter_state"
CANONICAL_TRUTH_TARGET = "ais_event_remaining_restoration_minutes"


def evaluate_sample_messages(path: str | Path, districts: tuple[str, ...]) -> dict[str, Any]:
    source = Path(path)
    total = parsed = passed = 0
    failures = []
    for line_no, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        total += 1
        item = json.loads(line)
        expected = item.get("expected", {})
        event = parse_webex_message(item, districts=districts)
        if expected.get("ignored"):
            if event is None:
                passed += 1
            else:
                parsed += 1
                failures.append({"line": line_no, "id": item.get("id"), "reason": "expected_ignored"})
            continue
        if event is None:
            failures.append({"line": line_no, "id": item.get("id"), "reason": "not_parsed"})
            continue
        parsed += 1
        actual = {
            "device_id": event.outage_device.device_id,
            "device_type": event.outage_device.device_type,
            "feeder": event.outage_device.feeder,
            "district": event.district,
            "event_number": event.parsed_fields.get("event_number"),
            "event_number_missing_reason": event.parsed_fields.get("event_number_missing_reason"),
            "event_time_source": event.parsed_fields.get("event_time_source"),
            "webex_device_interruption_class": event.parsed_fields.get("webex_device_interruption_class"),
            "webex_open_close_minutes": event.parsed_fields.get("webex_open_close_minutes"),
        }
        mismatches = {
            key: {"expected": value, "actual": actual.get(key)}
            for key, value in expected.items()
            if actual.get(key) != value
        }
        if mismatches:
            failures.append({"line": line_no, "id": item.get("id"), "mismatches": mismatches})
        else:
            passed += 1
    return {
        "source": str(source),
        "total": total,
        "parsed": parsed,
        "passed": passed,
        "failed": len(failures),
        "parser_success_rate": round(parsed / total, 3) if total else None,
        "expectation_pass_rate": round(passed / total, 3) if total else None,
        "failures": failures[:20],
    }


def _prediction_rows(db_path: str | Path) -> pd.DataFrame:
    path = Path(db_path)
    if not path.exists():
        return pd.DataFrame()
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        query = """
            WITH latest_notifications AS (
                SELECT n.*
                FROM notifications n
                JOIN (
                    SELECT event_id, MAX(id) AS max_id
                    FROM notifications
                    GROUP BY event_id
                ) latest ON latest.max_id = n.id
            )
            SELECT
                p.event_id,
                p.model_version,
                p.etr_minutes_p50,
                p.q25,
                p.q75,
                p.q10,
                p.q90,
                p.risk_level,
                p.match_confidence,
                p.affected_count,
                p.created_at AS predicted_at,
                e.webex_message_id,
                e.room_id,
                e.raw_text,
                e.parsed_json,
                n.status AS notification_status,
                n.status_code AS notification_status_code
            FROM predictions p
            LEFT JOIN outage_events e ON e.event_id = p.event_id
            LEFT JOIN latest_notifications n ON n.event_id = p.event_id
            ORDER BY p.created_at
        """
        return pd.read_sql_query(query, conn)
    finally:
        conn.close()


def build_shadow_report(
    db_path: str | Path,
    event_file: str | Path,
    etr_files: list[str | Path] | tuple[str | Path, ...],
    distance_file: str | Path,
    output_csv: str | Path | None = None,
    truth_mapping_path: str | Path | None = None,
) -> dict[str, Any]:
    preds = _prediction_rows(db_path)
    truth_mapping = _load_truth_mapping(truth_mapping_path)
    if preds.empty:
        summary = {
            "predictions": 0,
            "with_event_number": 0,
            "with_truth": 0,
            "mapped_truth_rows": int(truth_mapping["actual_restoration_minutes"].notna().sum()),
            "match_coverage": None,
            "q50_mae_minutes": None,
            "q10_q90_coverage": None,
            "output_csv": str(output_csv) if output_csv else None,
            "truth_mapping": str(truth_mapping_path) if truth_mapping_path else None,
        }
        if output_csv:
            Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame().to_csv(output_csv, index=False, encoding="utf-8-sig")
        return summary

    preds["event_number"] = preds["parsed_json"].apply(_event_number_from_json)
    report = _apply_truth_mapping(preds, truth_mapping)
    mapped_actual = pd.to_numeric(report["mapped_actual_restoration_minutes"], errors="coerce")
    mapped_source = _mapped_or_default(report, "mapped_truth_source", "")
    mapped_target = _mapped_or_default(report, "mapped_truth_target", "")
    mapped_quality = _mapped_or_default(report, "mapped_truth_quality", "").str.upper()
    eligible = (
        mapped_actual.notna()
        & mapped_source.eq(CANONICAL_TRUTH_SOURCE)
        & mapped_target.eq(CANONICAL_TRUTH_TARGET)
        & mapped_quality.isin({"OK", "HIGH", "STRICT"})
        & mapped_actual.gt(0)
        & mapped_actual.le(1440)
    )
    report["target_etr_minutes"] = mapped_actual.where(eligible)
    report["truth_source"] = mapped_source.where(eligible)
    report["truth_target"] = mapped_target.where(eligible)
    report["truth_definition"] = _mapped_or_default(report, "mapped_truth_definition", "").where(eligible)
    report["truth_quality"] = mapped_quality.where(eligible)
    report["truth_notes"] = _mapped_or_default(report, "mapped_truth_notes", "").where(eligible)
    report["training_eligibility"] = eligible.map({True: "train_eligible", False: "context_only"})
    report["absolute_error_minutes"] = (
        pd.to_numeric(report["etr_minutes_p50"], errors="coerce")
        - pd.to_numeric(report["target_etr_minutes"], errors="coerce")
    ).abs()
    actual = pd.to_numeric(report["target_etr_minutes"], errors="coerce")
    report["covered_q10_q90"] = (
        (actual >= pd.to_numeric(report["q10"], errors="coerce"))
        & (actual <= pd.to_numeric(report["q90"], errors="coerce"))
    )
    with_truth = report["target_etr_minutes"].notna()
    if output_csv:
        output = Path(output_csv)
        output.parent.mkdir(parents=True, exist_ok=True)
        report.to_csv(output, index=False, encoding="utf-8-sig")
    return {
        "predictions": int(len(report)),
        "with_event_number": int(report["event_number"].notna().sum()),
        "with_truth": int(with_truth.sum()),
        "mapped_truth_rows": int(mapped_actual.notna().sum()),
        "eligible_truth_rows": int(eligible.sum()),
        "excluded_truth_rows": int((mapped_actual.notna() & ~eligible).sum()),
        "match_coverage": round(float((report["affected_count"] > 0).mean()), 3) if len(report) else None,
        "q50_mae_minutes": (
            round(float(report.loc[with_truth, "absolute_error_minutes"].mean()), 2)
            if with_truth.any()
            else None
        ),
        "q10_q90_coverage": (
            round(float(report.loc[with_truth, "covered_q10_q90"].mean()), 3)
            if with_truth.any()
            else None
        ),
        "notification_status": report["notification_status"].fillna("<missing>").value_counts().to_dict(),
        "output_csv": str(output_csv) if output_csv else None,
        "truth_mapping": str(truth_mapping_path) if truth_mapping_path else None,
    }


def export_shadow_truth_template(db_path: str | Path, output_csv: str | Path) -> dict[str, Any]:
    preds = _prediction_rows(db_path)
    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_truth_mapping(output)
    existing_by_message = {
        row["webex_message_id"]: row
        for row in existing.to_dict(orient="records")
        if row.get("webex_message_id")
    }
    message_ids = []
    if not preds.empty and "webex_message_id" in preds.columns:
        message_ids = sorted(
            {
                str(value)
                for value in preds["webex_message_id"].dropna().tolist()
                if str(value).strip()
            }
        )
    rows = []
    for message_id in message_ids:
        previous = existing_by_message.get(message_id, {})
        rows.append(
            {
                "webex_message_id": message_id,
                "event_number": previous.get("event_number") or "",
                "actual_restoration_minutes": previous.get("actual_restoration_minutes") or "",
                "truth_source": previous.get("truth_source") or "",
                "truth_target": previous.get("truth_target") or "",
                "truth_definition": previous.get("truth_definition") or "",
                "truth_quality": previous.get("truth_quality") or "",
                "truth_notes": previous.get("truth_notes") or "",
            }
        )
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(TRUTH_MAPPING_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    filled_actual = sum(1 for row in rows if str(row["actual_restoration_minutes"]).strip())
    filled_event_number = sum(1 for row in rows if str(row["event_number"]).strip())
    return {
        "output_csv": str(output),
        "rows": len(rows),
        "filled_event_number": filled_event_number,
        "filled_actual_restoration_minutes": filled_actual,
    }


def _event_number_from_json(raw: object) -> str | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    fields = data.get("parsed_fields") or {}
    value = fields.get("event_number")
    return str(value) if value else None


def _load_truth_mapping(path: str | Path | None) -> pd.DataFrame:
    columns = list(TRUTH_MAPPING_COLUMNS)
    if not path or not Path(path).exists():
        return pd.DataFrame(columns=columns)
    mapping = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    missing = [column for column in TRUTH_MAPPING_REQUIRED_COLUMNS if column not in mapping.columns]
    if missing:
        raise ValueError(f"Truth mapping is missing required columns: {', '.join(missing)}")
    for column in columns:
        if column not in mapping.columns:
            mapping[column] = ""
    mapping = mapping[columns].copy()
    mapping["webex_message_id"] = mapping["webex_message_id"].astype(str).str.strip()
    mapping["event_number"] = mapping["event_number"].astype(str).str.strip().replace("", pd.NA)
    mapping["actual_restoration_minutes"] = pd.to_numeric(
        mapping["actual_restoration_minutes"].astype(str).str.strip().replace("", pd.NA),
        errors="coerce",
    )
    for column in columns[3:]:
        mapping[column] = mapping[column].astype(str).str.strip()
    mapping = mapping[mapping["webex_message_id"] != ""]
    return mapping.drop_duplicates(subset=["webex_message_id"], keep="last")


def _apply_truth_mapping(preds: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    if mapping.empty:
        report = preds.copy()
        report["mapped_event_number"] = pd.NA
        report["mapped_actual_restoration_minutes"] = pd.NA
        report["mapped_truth_source"] = pd.NA
        report["mapped_truth_target"] = pd.NA
        report["mapped_truth_definition"] = pd.NA
        report["mapped_truth_quality"] = pd.NA
        report["mapped_truth_notes"] = pd.NA
        return report
    renamed = mapping.rename(
        columns={
            "event_number": "mapped_event_number",
            "actual_restoration_minutes": "mapped_actual_restoration_minutes",
            "truth_source": "mapped_truth_source",
            "truth_target": "mapped_truth_target",
            "truth_definition": "mapped_truth_definition",
            "truth_quality": "mapped_truth_quality",
            "truth_notes": "mapped_truth_notes",
        }
    )
    report = preds.merge(renamed, on="webex_message_id", how="left")
    report["event_number"] = report["event_number"].where(
        report["event_number"].notna() & (report["event_number"].astype(str).str.strip() != ""),
        report["mapped_event_number"],
    )
    return report


def _mapped_or_default(report: pd.DataFrame, column: str, default: str) -> pd.Series:
    if column not in report.columns:
        return pd.Series([default] * len(report), index=report.index)
    values = report[column].fillna("").astype(str).str.strip()
    return values.mask(values == "", default)
