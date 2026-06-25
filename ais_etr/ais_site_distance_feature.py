from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable


SITE_ID_ALIASES = (
    "site_ref",
    "site_id",
    "siteid",
    "location_id",
    "locationid",
    "location id",
    "ais_location_id",
    "cell_site",
    "cellsite",
)

FEATURE_COLUMNS = (
    "nearest_pea_office_name",
    "nearest_pea_office_size",
    "nearest_pea_office_road_distance_km",
    "nearest_pea_office_round_trip_km",
    "nearest_pea_office_round_trip_band",
    "nearest_pea_office_oneway_over_25km",
    "nearest_pea_office_straight_line_km",
    "nearest_pea_office_osrm_duration_min",
    "nearest_pea_office_route_status",
    "nearest_pea_office_feature_status",
)

SENSITIVE_COLUMN_PATTERNS = (
    "peano",
    "pea_no",
    "meter",
    "หมายเลขเครื่องวัด",
    "เครื่องวัด",
    "customer",
    "ca_number",
    "contract_account",
    "roomid",
    "room_id",
    "token",
    "secret",
    "raw_text",
    "markdown",
    "source_file",
    "notes",
    "note",
    "remark",
)


@dataclass(frozen=True)
class DistanceCandidate:
    site_key: str
    row: dict[str, str]
    road_distance_km: float | None


def build_ais_site_distance_features(
    source_csv: str | Path,
    distance_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    site_id_column: str | None = None,
) -> dict[str, Any]:
    source_path = Path(source_csv)
    distance_path = Path(distance_csv)
    if not source_path.exists():
        raise FileNotFoundError(f"AIS failed-site source CSV not found: {source_path}")
    if not distance_path.exists():
        raise FileNotFoundError(f"AIS site distance CSV not found: {distance_path}")
    source_rows = _read_csv(source_path)
    if not source_rows:
        _write_csv(output_csv, FEATURE_COLUMNS, [])
        summary = _summary(
            source_path,
            distance_path,
            output_csv,
            markdown_output,
            source_rows=[],
            output_rows=[],
            site_column=site_id_column or "",
            distance_rows=0,
        )
        if markdown_output:
            _write_markdown(markdown_output, summary)
        return summary

    site_column = site_id_column or _detect_site_column(source_rows[0].keys())
    if not site_column:
        raise ValueError("Cannot find AIS site id column. Expected one of: " + ", ".join(SITE_ID_ALIASES))

    distance_lookup, distance_rows = _load_distance_lookup(distance_path)
    source_columns = [column for column in source_rows[0].keys() if not _is_sensitive_column(column)]
    output_columns = _unique([*source_columns, *FEATURE_COLUMNS])
    output_rows = []
    for row in source_rows:
        site_key = _normalize_site_key(row.get(site_column))
        match = _match_distance(site_key, distance_lookup)
        output_row = {column: row.get(column, "") for column in source_columns}
        output_row.update(_feature_values(site_key, match))
        output_rows.append(output_row)

    _write_csv(output_csv, output_columns, output_rows)
    summary = _summary(
        source_path,
        distance_path,
        output_csv,
        markdown_output,
        source_rows=source_rows,
        output_rows=output_rows,
        site_column=site_column,
        distance_rows=distance_rows,
    )
    if markdown_output:
        _write_markdown(markdown_output, summary)
    return summary


def _load_distance_lookup(distance_path: Path) -> tuple[dict[str, list[DistanceCandidate]], int]:
    rows = _read_csv(distance_path)
    if not rows:
        return {}, 0
    key_column = _detect_site_column(rows[0].keys())
    if not key_column:
        raise ValueError("Cannot find site key column in distance CSV")
    lookup: dict[str, list[DistanceCandidate]] = {}
    for row in rows:
        site_key = _normalize_site_key(row.get(key_column))
        if not site_key:
            continue
        candidate = DistanceCandidate(
            site_key=site_key,
            row=row,
            road_distance_km=_optional_float(
                row.get("road_distance_km") or row.get("nearest_pea_office_road_distance_km")
            ),
        )
        lookup.setdefault(site_key, []).append(candidate)
        base_key = _base_site_key(site_key)
        if base_key != site_key:
            lookup.setdefault(base_key, []).append(candidate)
    return lookup, len(rows)


def _match_distance(site_key: str, lookup: dict[str, list[DistanceCandidate]]) -> tuple[str, DistanceCandidate | None]:
    if not site_key:
        return "missing_site_id", None
    candidates = lookup.get(site_key) or []
    if not candidates:
        return "no_distance_match", None
    selected = min(
        candidates,
        key=lambda candidate: (
            candidate.road_distance_km is None,
            candidate.road_distance_km if candidate.road_distance_km is not None else float("inf"),
            candidate.site_key,
        ),
    )
    if len(candidates) > 1:
        return "matched_duplicate_site_ref_min_distance", selected
    return "matched", selected


def _feature_values(site_key: str, match: tuple[str, DistanceCandidate | None]) -> dict[str, str]:
    status, candidate = match
    if candidate is None:
        return {
            "nearest_pea_office_name": "",
            "nearest_pea_office_size": "",
            "nearest_pea_office_road_distance_km": "",
            "nearest_pea_office_round_trip_km": "",
            "nearest_pea_office_round_trip_band": "",
            "nearest_pea_office_oneway_over_25km": "",
            "nearest_pea_office_straight_line_km": "",
            "nearest_pea_office_osrm_duration_min": "",
            "nearest_pea_office_route_status": "",
            "nearest_pea_office_feature_status": status,
        }

    row = candidate.row
    road = candidate.road_distance_km
    round_trip = road * 2 if road is not None else None
    route_status = row.get("route_status") or row.get("nearest_pea_office_route_status") or ""
    if route_status and route_status != "ok" and status == "matched":
        status = f"matched_route_{route_status}"
    return {
        "nearest_pea_office_name": row.get("nearest_pea_office") or row.get("nearest_pea_office_name") or "",
        "nearest_pea_office_size": row.get("nearest_office_size") or row.get("nearest_pea_office_size") or "",
        "nearest_pea_office_road_distance_km": _fmt(road),
        "nearest_pea_office_round_trip_km": _fmt(round_trip),
        "nearest_pea_office_round_trip_band": _round_trip_band(round_trip),
        "nearest_pea_office_oneway_over_25km": _bool(road is not None and road > 25),
        "nearest_pea_office_straight_line_km": _fmt(
            _optional_float(row.get("straight_line_km") or row.get("nearest_pea_office_straight_line_km"))
        ),
        "nearest_pea_office_osrm_duration_min": _fmt(
            _optional_float(row.get("osrm_duration_min") or row.get("nearest_pea_office_osrm_duration_min"))
        ),
        "nearest_pea_office_route_status": route_status,
        "nearest_pea_office_feature_status": status,
    }


def _summary(
    source_path: Path,
    distance_path: Path,
    output_csv: str | Path,
    markdown_output: str | Path | None,
    *,
    source_rows: list[dict[str, str]],
    output_rows: list[dict[str, str]],
    site_column: str,
    distance_rows: int,
) -> dict[str, Any]:
    statuses = Counter(row.get("nearest_pea_office_feature_status", "") for row in output_rows)
    bands = Counter(row.get("nearest_pea_office_round_trip_band", "") for row in output_rows)
    matched_rows = sum(
        count
        for status, count in statuses.items()
        if status.startswith("matched")
    )
    road_values = [
        value
        for value in (_optional_float(row.get("nearest_pea_office_road_distance_km")) for row in output_rows)
        if value is not None
    ]
    return {
        "source_csv": str(source_path),
        "distance_csv": str(distance_path),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "rows": len(source_rows),
        "distance_rows": distance_rows,
        "site_id_column": site_column,
        "matched_rows": matched_rows,
        "missing_site_id_rows": statuses.get("missing_site_id", 0),
        "no_distance_match_rows": statuses.get("no_distance_match", 0),
        "feature_status_counts": dict(statuses),
        "round_trip_band_counts": dict(bands),
        "max_oneway_road_distance_km": max(road_values) if road_values else None,
        "feature_columns": list(FEATURE_COLUMNS),
        "redaction_policy": "drops PEANO, meter, customer, room, token/secret, raw text, source file path, and notes-like columns",
    }


def _write_markdown(path: str | Path, summary: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# AIS Site Distance Feature",
        "",
        "Feature source: nearest road distance from each AIS failed site to the nearest PEA office in the supplied distance lookup.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Source rows | {summary['rows']} |",
        f"| Matched rows | {summary['matched_rows']} |",
        f"| Missing site id rows | {summary['missing_site_id_rows']} |",
        f"| No distance match rows | {summary['no_distance_match_rows']} |",
        f"| Max one-way road distance km | {_blank(summary['max_oneway_road_distance_km'])} |",
        "",
        "## Round Trip Bands",
        "",
        "| Band | Rows |",
        "| --- | ---: |",
    ]
    for band, count in summary["round_trip_band_counts"].items():
        lines.append(f"| `{band or '<blank>'}` | {count} |")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Output is a feature table only; AIS outage/restore remains the restoration truth label.",
            "- PEA office distance is allowed as context/feature, not as proof of restoration time.",
            "- Sensitive PEANO, meter, customer, room, token/secret, raw text, and notes-like columns are dropped.",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp874"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                return [
                    {key: (value or "") for key, value in row.items() if key is not None}
                    for row in csv.DictReader(handle)
                ]
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return []


def _write_csv(path: str | Path, columns: Iterable[str], rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _detect_site_column(columns: Iterable[str]) -> str:
    normalized = {_normalize_header(column): column for column in columns}
    for alias in SITE_ID_ALIASES:
        column = normalized.get(_normalize_header(alias))
        if column:
            return column
    return ""


def _is_sensitive_column(column: str) -> bool:
    normalized = _normalize_header(column)
    return any(_normalize_header(pattern) in normalized for pattern in SENSITIVE_COLUMN_PATTERNS)


def _normalize_header(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s\-.#/()]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _normalize_site_key(value: Any) -> str:
    text = str(value or "").strip()
    if text.lower() in {"", "nan", "none", "null"}:
        return ""
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return re.sub(r"\s+", "", text).upper()


def _base_site_key(value: str) -> str:
    return re.sub(r"__COORD\d+$", "", value, flags=re.IGNORECASE)


def _optional_float(value: Any) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _round_trip_band(value: float | None) -> str:
    if value is None:
        return ""
    if value <= 50:
        return "0-50"
    if value <= 100:
        return "51-100"
    if value <= 150:
        return "101-150"
    return "151+"


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    rounded = round(value, 3)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded).rstrip("0").rstrip(".")


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _blank(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, float):
        return _fmt(value)
    return str(value)


def _unique(values: Iterable[str]) -> list[str]:
    output = []
    seen = set()
    for value in values:
        if value in seen:
            continue
        output.append(value)
        seen.add(value)
    return output
