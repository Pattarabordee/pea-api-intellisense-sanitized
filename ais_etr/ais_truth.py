from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from statistics import mean, median
from typing import Any, Iterable

from .evaluation import TRUTH_MAPPING_COLUMNS
from .utils import normalize_device_id, normalize_feeder

try:
    import pandas as pd
except Exception:  # pragma: no cover - exercised only when optional xlsx support is missing
    pd = None  # type: ignore[assignment]


AIS_TRUTH_INPUT_COLUMNS = (
    "site_id",
    "peano",
    "outage_start_time",
    "power_restore_time",
    "event_number",
    "device_id",
    "feeder",
    "source",
    "notes",
)

AIS_TRUTH_COLUMNS = (
    "site_id",
    "peano",
    "outage_start_time",
    "power_restore_time",
    "actual_restoration_minutes",
    "event_number",
    "device_id",
    "feeder",
    "source",
    "truth_source",
    "truth_target",
    "truth_definition",
    "truth_quality",
    "truth_notes",
    "source_file",
    "source_row_number",
)

AIS_TRUTH_MATCH_AUDIT_COLUMNS = (
    "webex_message_id",
    "webex_event_time",
    "webex_event_number",
    "webex_device_id",
    "webex_feeder",
    "match_status",
    "match_level",
    "matched_ais_rows",
    "matched_site_count",
    "matched_peano_count",
    "actual_restoration_minutes",
    "selected_event_number",
    "truth_quality",
    "truth_notes",
)

AIS_TRUTH_TARGET = "ais_site_actual_restoration_minutes"
AIS_TRUTH_DEFINITION = "AIS_POWER_RESTORE_TIME - AIS_POWER_OUTAGE_TIME"
AIS_TRUTH_SOURCE_DEFAULT = "ais_site_power_status"
INVALID_QUALITIES = {
    "MISSING_ASSET_ID",
    "MISSING_OUTAGE_START",
    "MISSING_RESTORE",
    "INVALID_NEGATIVE",
    "INVALID_LONG",
}

_EMPTY_VALUES = {"", "-", "nan", "none", "null", "nat"}
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
)

_ALIASES = {
    "site_id": {
        "site_id",
        "siteid",
        "site",
        "ais_site_id",
        "cell_site",
        "cellsite",
        "station_id",
    },
    "peano": {
        "peano",
        "pea_no",
        "peano.",
        "pea_number",
        "meter_no",
        "meter_number",
        "meter",
    },
    "outage_start_time": {
        "outage_start_time",
        "power_outage_time",
        "ais_power_outage_time",
        "start_time",
        "down_time",
        "power_down_time",
        "outage_time",
    },
    "power_restore_time": {
        "power_restore_time",
        "ais_power_restore_time",
        "restore_time",
        "restored_time",
        "power_restored_time",
        "power_up_time",
        "up_time",
    },
    "event_number": {"event_number", "event_no", "event_id", "eventid"},
    "device_id": {"device_id", "device", "outage_device", "protection_device"},
    "feeder": {"feeder", "feeder_id", "feedercode"},
    "source": {"source", "data_source"},
    "notes": {"notes", "note", "remark", "remarks"},
}


@dataclass(frozen=True)
class AisTruthRow:
    site_id: str
    peano: str
    outage_start_time: datetime | None
    power_restore_time: datetime | None
    event_number: str
    device_id: str
    feeder: str
    source: str
    notes: str
    source_file: str
    source_row_number: int

    @property
    def actual_restoration_minutes(self) -> float | None:
        if self.outage_start_time is None or self.power_restore_time is None:
            return None
        return round((self.power_restore_time - self.outage_start_time).total_seconds() / 60, 2)

    @property
    def truth_quality(self) -> str:
        if not self.site_id and not self.peano:
            return "MISSING_ASSET_ID"
        if self.outage_start_time is None:
            return "MISSING_OUTAGE_START"
        if self.power_restore_time is None:
            return "MISSING_RESTORE"
        actual = self.actual_restoration_minutes
        if actual is None:
            return "MISSING_RESTORE"
        if actual < 0:
            return "INVALID_NEGATIVE"
        if actual > 1440:
            return "INVALID_LONG"
        if actual <= 5:
            return "REVIEW_SHORT"
        return "OK"

    def asdict(self) -> dict[str, str]:
        actual = self.actual_restoration_minutes
        return {
            "site_id": self.site_id,
            "peano": self.peano,
            "outage_start_time": _format_dt(self.outage_start_time),
            "power_restore_time": _format_dt(self.power_restore_time),
            "actual_restoration_minutes": "" if actual is None else str(actual),
            "event_number": self.event_number,
            "device_id": self.device_id,
            "feeder": self.feeder,
            "source": self.source,
            "truth_source": AIS_TRUTH_SOURCE_DEFAULT,
            "truth_target": AIS_TRUTH_TARGET,
            "truth_definition": AIS_TRUTH_DEFINITION,
            "truth_quality": self.truth_quality,
            "truth_notes": self.notes,
            "source_file": self.source_file,
            "source_row_number": str(self.source_row_number),
        }


def write_ais_truth_template(output_csv: str | Path, include_example: bool = False, force: bool = False) -> dict[str, Any]:
    output = Path(output_csv)
    if output.exists() and not force:
        return {"output_csv": str(output), "status": "exists", "columns": list(AIS_TRUTH_INPUT_COLUMNS)}
    output.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    if include_example:
        rows.append(
            {
                "site_id": "AIS_SITE_001",
                "peano": "REDACTED-METER-0000",
                "outage_start_time": "2026-06-17 10:00:00",
                "power_restore_time": "2026-06-17 10:45:00",
                "event_number": "",
                "device_id": "",
                "feeder": "",
                "source": "AIS",
                "notes": "example row; replace before import",
            }
        )
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(AIS_TRUTH_INPUT_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return {
        "output_csv": str(output),
        "status": "created",
        "columns": list(AIS_TRUTH_INPUT_COLUMNS),
        "example_rows": len(rows),
    }


def import_ais_truth(
    source: str | Path,
    output_csv: str | Path,
    rejects_csv: str | Path | None = None,
    sheet: str | int | None = None,
) -> dict[str, Any]:
    source_path = Path(source)
    raw_rows, mapped_columns = _read_source(source_path, sheet=sheet)
    rows = [_row_from_mapping(row, source_path, source_row_number) for source_row_number, row in raw_rows]

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(AIS_TRUTH_COLUMNS))
        writer.writeheader()
        writer.writerows(row.asdict() for row in rows)

    reject_rows = [row.asdict() for row in rows if row.truth_quality in INVALID_QUALITIES]
    if rejects_csv:
        rejects = Path(rejects_csv)
        rejects.parent.mkdir(parents=True, exist_ok=True)
        with rejects.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(AIS_TRUTH_COLUMNS))
            writer.writeheader()
            writer.writerows(reject_rows)

    quality_counts: dict[str, int] = {}
    for row in rows:
        quality_counts[row.truth_quality] = quality_counts.get(row.truth_quality, 0) + 1
    duplicate_key_rows = _count_duplicate_key_rows(rows)
    return {
        "source": str(source_path),
        "output_csv": str(output),
        "rejects_csv": str(rejects_csv) if rejects_csv else None,
        "rows": len(rows),
        "valid_rows": sum(1 for row in rows if row.truth_quality == "OK"),
        "review_rows": sum(1 for row in rows if row.truth_quality == "REVIEW_SHORT"),
        "invalid_rows": len(reject_rows),
        "duplicate_key_rows": duplicate_key_rows,
        "truth_target": AIS_TRUTH_TARGET,
        "truth_definition": AIS_TRUTH_DEFINITION,
        "quality_counts": quality_counts,
        "mapped_columns": mapped_columns,
    }


def match_ais_truth_to_shadow(
    db_path: str | Path,
    ais_truth_csv: str | Path,
    mapping_csv: str | Path,
    audit_csv: str | Path | None = None,
    max_window_minutes: float = 1440.0,
    ambiguity_delta_minutes: float = 5.0,
    aggregation: str = "max",
    include_review: bool = False,
    allow_feeder: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    runtime_rows = _runtime_shadow_rows(db_path)
    truth_rows = _load_canonical_ais_truth(ais_truth_csv)
    eligible_qualities = {"OK"} | ({"REVIEW_SHORT"} if include_review else set())
    eligible_rows = [
        row
        for row in truth_rows
        if row.get("actual_float") is not None and row.get("truth_quality") in eligible_qualities
    ]
    mapping_rows = _load_or_create_truth_mapping(mapping_csv, runtime_rows)
    mapping_by_message = {row["webex_message_id"]: row for row in mapping_rows}

    audit_rows: list[dict[str, Any]] = []
    filled_rows = 0
    preserved_existing_rows = 0
    matched_rows = 0
    no_match_rows = 0
    feeder_candidate_rows = 0

    for runtime in runtime_rows:
        decision = _match_one_shadow_event(
            runtime,
            eligible_rows,
            max_window_minutes=max_window_minutes,
            ambiguity_delta_minutes=ambiguity_delta_minutes,
            aggregation=aggregation,
            allow_feeder=allow_feeder,
        )
        audit_rows.append(decision)
        status = decision.get("match_status")
        if status == "matched":
            matched_rows += 1
        elif status == "feeder_candidate_only":
            feeder_candidate_rows += 1
        else:
            no_match_rows += 1

        message_id = runtime.get("webex_message_id") or ""
        mapping = mapping_by_message.get(message_id)
        if mapping is None or status != "matched":
            continue
        if not overwrite and str(mapping.get("actual_restoration_minutes", "")).strip():
            preserved_existing_rows += 1
            continue
        mapping["event_number"] = decision.get("selected_event_number") or runtime.get("event_number") or ""
        mapping["actual_restoration_minutes"] = str(decision.get("actual_restoration_minutes") or "")
        mapping["truth_source"] = AIS_TRUTH_SOURCE_DEFAULT
        mapping["truth_target"] = AIS_TRUTH_TARGET
        mapping["truth_definition"] = AIS_TRUTH_DEFINITION
        mapping["truth_quality"] = str(decision.get("truth_quality") or "")
        mapping["truth_notes"] = str(decision.get("truth_notes") or "")
        filled_rows += 1

    _write_truth_mapping(mapping_csv, mapping_rows)
    if audit_csv:
        _write_match_audit(audit_csv, audit_rows)

    return {
        "db_path": str(db_path),
        "ais_truth_csv": str(ais_truth_csv),
        "mapping_output": str(mapping_csv),
        "audit_output": str(audit_csv) if audit_csv else None,
        "runtime_events": len(runtime_rows),
        "ais_truth_rows": len(truth_rows),
        "eligible_truth_rows": len(eligible_rows),
        "matched_rows": matched_rows,
        "filled_rows": filled_rows,
        "preserved_existing_rows": preserved_existing_rows,
        "no_match_rows": no_match_rows,
        "feeder_candidate_rows": feeder_candidate_rows,
        "include_review": include_review,
        "allow_feeder": allow_feeder,
        "aggregation": aggregation,
        "truth_target": AIS_TRUTH_TARGET,
    }


def _runtime_shadow_rows(db_path: str | Path) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
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
                e.webex_message_id,
                e.event_time,
                e.device_id,
                e.feeder,
                e.parsed_json,
                n.payload_json
            FROM outage_events e
            LEFT JOIN latest_notifications n ON n.event_id = e.event_id
            WHERE e.webex_message_id IS NOT NULL
            ORDER BY e.event_time, e.webex_message_id
        """
        rows = []
        for row in conn.execute(query).fetchall():
            item = dict(row)
            item["event_dt"] = _parse_datetime(item.get("event_time"))
            item["device_norm"] = normalize_device_id(item.get("device_id"))
            item["feeder_norm"] = normalize_feeder(item.get("feeder") or item.get("device_id"))
            item["event_number"] = _event_number_from_parsed_json(item.get("parsed_json"))
            item["affected_peanos"] = _affected_peanos(item.get("payload_json"))
            rows.append(item)
        return rows
    finally:
        conn.close()


def _load_canonical_ais_truth(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"AIS truth file not found: {source}")
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            outage_dt = _parse_datetime(row.get("outage_start_time"))
            actual = _optional_float(row.get("actual_restoration_minutes"))
            rows.append(
                {
                    **row,
                    "outage_start_dt": outage_dt,
                    "actual_float": actual,
                    "event_number_norm": _text(row.get("event_number")),
                    "device_norm": normalize_device_id(row.get("device_id")),
                    "feeder_norm": normalize_feeder(row.get("feeder") or row.get("device_id")),
                    "peano_norm": _normalize_key(row.get("peano")),
                    "site_id_norm": _normalize_key(row.get("site_id")),
                    "truth_quality": _text(row.get("truth_quality")),
                }
            )
    return rows


def _match_one_shadow_event(
    runtime: dict[str, Any],
    ais_rows: list[dict[str, Any]],
    max_window_minutes: float,
    ambiguity_delta_minutes: float,
    aggregation: str,
    allow_feeder: bool,
) -> dict[str, Any]:
    base = {
        "webex_message_id": runtime.get("webex_message_id") or "",
        "webex_event_time": _format_dt(runtime.get("event_dt")),
        "webex_event_number": runtime.get("event_number") or "",
        "webex_device_id": runtime.get("device_norm") or "",
        "webex_feeder": runtime.get("feeder_norm") or "",
        "match_status": "no_match",
        "match_level": "",
        "matched_ais_rows": 0,
        "matched_site_count": 0,
        "matched_peano_count": 0,
        "actual_restoration_minutes": "",
        "selected_event_number": "",
        "truth_quality": "",
        "truth_notes": "no AIS truth candidate",
    }
    event_dt = runtime.get("event_dt")
    if event_dt is None:
        return {**base, "truth_notes": "missing Webex event time"}

    event_number = runtime.get("event_number")
    if event_number:
        candidates = [
            (0.0, row)
            for row in ais_rows
            if row.get("event_number_norm") == event_number
            and _within_window(event_dt, row.get("outage_start_dt"), max_window_minutes)
        ]
        if candidates:
            return _aggregate_candidate_decision(base, candidates, "event_number", aggregation)

    affected_peanos = runtime.get("affected_peanos") or set()
    if affected_peanos:
        candidates = _rank_ais_candidates(
            ais_rows,
            event_dt,
            max_window_minutes,
            lambda row: bool(row.get("peano_norm") and row.get("peano_norm") in affected_peanos),
        )
        selected = _candidate_cluster(candidates, ambiguity_delta_minutes)
        if selected:
            return _aggregate_candidate_decision(base, selected, "affected_peano_time", aggregation)

    device = runtime.get("device_norm")
    if device:
        candidates = _rank_ais_candidates(
            ais_rows,
            event_dt,
            max_window_minutes,
            lambda row: row.get("device_norm") == device,
        )
        selected = _candidate_cluster(candidates, ambiguity_delta_minutes)
        if selected:
            return _aggregate_candidate_decision(base, selected, "device_time", aggregation)

    feeder = runtime.get("feeder_norm")
    if feeder:
        candidates = _rank_ais_candidates(
            ais_rows,
            event_dt,
            min(max_window_minutes, 360.0),
            lambda row: bool(row.get("feeder_norm") and row.get("feeder_norm") == feeder),
        )
        selected = _candidate_cluster(candidates, ambiguity_delta_minutes)
        if selected:
            decision = _aggregate_candidate_decision(base, selected, "feeder_time", aggregation)
            if allow_feeder:
                return decision
            decision["match_status"] = "feeder_candidate_only"
            decision["truth_notes"] = f"{decision['truth_notes']}; feeder match not auto-filled"
            return decision

    return base


def _rank_ais_candidates(
    ais_rows: list[dict[str, Any]],
    event_dt: datetime,
    max_window_minutes: float,
    predicate,
) -> list[tuple[float, dict[str, Any]]]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in ais_rows:
        start = row.get("outage_start_dt")
        if start is None or not predicate(row):
            continue
        delta = abs((start - event_dt).total_seconds() / 60)
        if delta <= max_window_minutes:
            candidates.append((round(delta, 3), row))
    return sorted(candidates, key=lambda item: (item[0], str(item[1].get("source_row_number") or "")))


def _candidate_cluster(
    candidates: list[tuple[float, dict[str, Any]]],
    ambiguity_delta_minutes: float,
) -> list[tuple[float, dict[str, Any]]]:
    if not candidates:
        return []
    best_delta = candidates[0][0]
    return [
        candidate
        for candidate in candidates
        if candidate[0] - best_delta <= ambiguity_delta_minutes
    ]


def _aggregate_candidate_decision(
    base: dict[str, Any],
    candidates: list[tuple[float, dict[str, Any]]],
    match_level: str,
    aggregation: str,
) -> dict[str, Any]:
    rows = [row for _delta, row in candidates if row.get("actual_float") is not None]
    deltas = [delta for delta, row in candidates if row.get("actual_float") is not None]
    values = [float(row["actual_float"]) for row in rows]
    actual = _aggregate_values(values, aggregation)
    event_numbers = sorted({str(row.get("event_number") or "").strip() for row in rows if str(row.get("event_number") or "").strip()})
    quality_values = sorted({str(row.get("truth_quality") or "").strip() for row in rows if str(row.get("truth_quality") or "").strip()})
    site_count = len({row.get("site_id_norm") for row in rows if row.get("site_id_norm")})
    peano_count = len({row.get("peano_norm") for row in rows if row.get("peano_norm")})
    cluster_id = _truth_cluster_id(rows)
    notes = (
        f"{match_level}; aggregation={aggregation}; ais_rows={len(rows)}; "
        f"sites={site_count}; peanos={peano_count}; truth_cluster_id={cluster_id}"
    )
    if deltas:
        notes += f"; best_delta_min={min(deltas):g}; max_delta_min={max(deltas):g}"
    if event_numbers:
        notes += f"; ais_event_numbers={len(event_numbers)}"
    return {
        **base,
        "match_status": "matched",
        "match_level": match_level,
        "matched_ais_rows": len(rows),
        "matched_site_count": site_count,
        "matched_peano_count": peano_count,
        "actual_restoration_minutes": "" if actual is None else str(actual),
        "selected_event_number": event_numbers[0] if len(event_numbers) == 1 else "",
        "truth_quality": "MIXED" if len(quality_values) > 1 else (quality_values[0] if quality_values else "OK"),
        "truth_notes": notes,
    }


def _aggregate_values(values: list[float], aggregation: str) -> float | None:
    if not values:
        return None
    mode = aggregation.strip().lower()
    if mode == "mean":
        return round(float(mean(values)), 2)
    if mode == "median":
        return round(float(median(values)), 2)
    if mode != "max":
        raise ValueError("aggregation must be one of: max, mean, median")
    return round(max(values), 2)


def _truth_cluster_id(rows: list[dict[str, Any]]) -> str:
    parts = sorted(
        {
            "|".join(
                [
                    str(row.get("outage_start_time") or ""),
                    str(row.get("power_restore_time") or ""),
                    str(row.get("actual_restoration_minutes") or ""),
                ]
            )
            for row in rows
        }
    )
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"ais-{digest}"


def _within_window(event_dt: datetime, candidate_dt: datetime | None, max_window_minutes: float) -> bool:
    if candidate_dt is None:
        return False
    return abs((candidate_dt - event_dt).total_seconds() / 60) <= max_window_minutes


def _event_number_from_parsed_json(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except Exception:
        return ""
    value = (data.get("parsed_fields") or {}).get("event_number")
    return _text(value)


def _affected_peanos(raw_payload: str | None) -> set[str]:
    if not raw_payload:
        return set()
    try:
        payload = json.loads(raw_payload)
    except Exception:
        return set()
    return {
        normalized
        for normalized in (_normalize_key(item.get("peano")) for item in payload.get("affected_customers") or [])
        if normalized
    }


def _load_or_create_truth_mapping(mapping_path: str | Path, runtime_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    path = Path(mapping_path)
    rows: list[dict[str, str]] = []
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                rows.append({column: (row.get(column) or "") for column in TRUTH_MAPPING_COLUMNS})
    existing = {row["webex_message_id"] for row in rows}
    for row in runtime_rows:
        message_id = row.get("webex_message_id") or ""
        if message_id and message_id not in existing:
            rows.append({column: "" for column in TRUTH_MAPPING_COLUMNS} | {"webex_message_id": message_id})
            existing.add(message_id)
    return rows


def _write_truth_mapping(mapping_path: str | Path, rows: list[dict[str, str]]) -> None:
    output = Path(mapping_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(TRUTH_MAPPING_COLUMNS))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in TRUTH_MAPPING_COLUMNS} for row in rows)


def _write_match_audit(output_path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(AIS_TRUTH_MATCH_AUDIT_COLUMNS))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in AIS_TRUTH_MATCH_AUDIT_COLUMNS} for row in rows)


def _read_source(source: Path, sheet: str | int | None = None) -> tuple[list[tuple[int, dict[str, Any]]], dict[str, str]]:
    suffix = source.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        rows = _read_excel(source, sheet=sheet)
    else:
        rows = _read_csv(source)
    if not rows:
        return [], {}
    canonical_headers = _canonical_header_map(rows[0][1].keys())
    mapped_columns = {
        canonical: original
        for canonical, original in canonical_headers.items()
        if original
    }
    output = []
    for source_row_number, row in rows:
        mapped = {}
        for canonical, original in canonical_headers.items():
            mapped[canonical] = row.get(original, "") if original else ""
        output.append((source_row_number, mapped))
    return output, mapped_columns


def _read_csv(source: Path) -> list[tuple[int, dict[str, Any]]]:
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp874"):
        try:
            with source.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                return [
                    (index, {key: value for key, value in row.items() if key is not None})
                    for index, row in enumerate(reader, start=2)
                ]
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


def _read_excel(source: Path, sheet: str | int | None = None) -> list[tuple[int, dict[str, Any]]]:
    if pd is None:
        raise RuntimeError("pandas is required to import Excel AIS truth files")
    frame = pd.read_excel(source, sheet_name=0 if sheet is None else sheet, dtype=str)
    frame = frame.fillna("")
    return [
        (index + 2, {str(column): row.get(column, "") for column in frame.columns})
        for index, row in frame.iterrows()
    ]


def _canonical_header_map(headers: Iterable[str]) -> dict[str, str]:
    normalized_to_original = {_normalize_header(header): str(header) for header in headers if str(header).strip()}
    output = {}
    for canonical in AIS_TRUTH_INPUT_COLUMNS:
        output[canonical] = ""
        for alias in (canonical, *_ALIASES.get(canonical, ())):
            original = normalized_to_original.get(_normalize_header(alias))
            if original:
                output[canonical] = original
                break
    return output


def _row_from_mapping(row: dict[str, Any], source: Path, source_row_number: int) -> AisTruthRow:
    return AisTruthRow(
        site_id=_text(row.get("site_id")),
        peano=_text(row.get("peano")),
        outage_start_time=_parse_datetime(row.get("outage_start_time")),
        power_restore_time=_parse_datetime(row.get("power_restore_time")),
        event_number=_text(row.get("event_number")),
        device_id=_text(row.get("device_id")).upper(),
        feeder=_text(row.get("feeder")).upper(),
        source=_text(row.get("source")) or "AIS",
        notes=_text(row.get("notes")),
        source_file=str(source),
        source_row_number=source_row_number,
    )


def _count_duplicate_key_rows(rows: list[AisTruthRow]) -> int:
    keys: dict[tuple[str, str, str, str], int] = {}
    for row in rows:
        key = (
            row.site_id,
            row.peano,
            _format_dt(row.outage_start_time),
            _format_dt(row.power_restore_time),
        )
        if key == ("", "", "", ""):
            continue
        keys[key] = keys.get(key, 0) + 1
    return sum(count for count in keys.values() if count > 1)


def _normalize_header(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s\-.#/()]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _normalize_key(value: Any) -> str:
    return re.sub(r"\s+", "", _text(value)).upper()


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in _EMPTY_VALUES:
        return ""
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return text


def _parse_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    numeric = _optional_float(text)
    if numeric is not None and 20000 <= numeric <= 80000:
        return datetime(1899, 12, 30) + timedelta(days=numeric)
    text = text.replace("T", " ")
    text = re.sub(r"Z$", "", text)
    if "." in text:
        head, tail = text.split(".", 1)
        digits = re.match(r"\d+", tail)
        if digits:
            text = head + "." + digits.group(0)[:6]
    for fmt in _DATETIME_FORMATS:
        try:
            return _normalize_buddhist_year(datetime.strptime(text, fmt))
        except ValueError:
            pass
    try:
        return _normalize_buddhist_year(datetime.fromisoformat(text))
    except ValueError:
        return None


def _normalize_buddhist_year(value: datetime) -> datetime:
    if value.year > 2400:
        value = value.replace(year=value.year - 543)
    return value.replace(tzinfo=None)


def _optional_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _format_dt(value: datetime | None) -> str:
    return value.isoformat(sep=" ") if value else ""
