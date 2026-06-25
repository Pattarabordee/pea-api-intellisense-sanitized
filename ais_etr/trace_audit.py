from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .registry import REGISTRY_SHEET
from .utils import normalize_device_id, normalize_feeder, split_device_list


TRACE_COLUMNS = [
    "priority_rank",
    "device_type",
    "device_id",
    "feeder",
    "event_count",
    "upstream_trace_result",
    "device_rows_in_source",
    "expected_device_rows_in_source",
    "expected_device_ok_rows",
    "feeder_rows_in_source",
    "feeder_ok_rows",
    "feeder_no_meter_rows",
    "same_station_ok_rows",
    "same_station_top_feeders",
    "source_status_counts_on_feeder",
    "source_status_counts_on_device",
    "evidence_level",
    "trace_interpretation",
    "next_action",
]


def trace_no_match_candidates_against_upstream(
    candidates_csv: str | Path,
    upstream_xlsx: str | Path,
    output_csv: str | Path,
    output_markdown: str | Path | None = None,
) -> dict[str, Any]:
    candidates = _read_candidates(candidates_csv)
    source = _load_upstream_rows(upstream_xlsx)
    rows = []
    for candidate in candidates:
        rows.append(_trace_candidate(candidate, source))

    output = Path(output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRACE_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    markdown_path = Path(output_markdown) if output_markdown else None
    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(_render_markdown(rows), encoding="utf-8-sig")

    return {
        "candidates": len(candidates),
        "output_csv": str(output),
        "output_markdown": str(markdown_path) if markdown_path else None,
        "trace_result_counts": dict(Counter(row["upstream_trace_result"] for row in rows)),
        "evidence_level_counts": dict(Counter(row["evidence_level"] for row in rows)),
    }


def _read_candidates(path: str | Path) -> list[dict[str, str]]:
    source = Path(path)
    with source.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _load_upstream_rows(path: str | Path) -> list[dict[str, Any]]:
    df = pd.read_excel(path, sheet_name=REGISTRY_SHEET, dtype=str).fillna("")
    status_col = _pick_column(df, ("status", "trace_status"), fallback_index=28)
    district_col = _pick_column(df, ("district", "amphoe"), fallback_index=8)
    rows = []
    for _, row in df.iterrows():
        feeder = normalize_feeder(_first(row.get("Feeder ID"), row.get("TX: Feeder")))
        status = _clean(row.get(status_col))
        devices_by_field = {
            "transformer": set(_devices_from_values(row.get("TX: FACILITYID"), row.get("TX: PEANO"))),
            "recloser": set(_devices_from_values(row.get("RC: FACILITYID"))),
            "switch": set(_devices_from_values(row.get("SW: FACILITYID"))),
            "cb": set(_devices_from_values(row.get("CB: FACILITYID"))),
        }
        all_devices = set().union(*devices_by_field.values())
        rows.append(
            {
                "feeder": feeder or "",
                "station_prefix": (feeder or "")[:3],
                "status": status,
                "is_ok": status.upper() == "OK",
                "is_no_meter": status.upper() == "NO_METER",
                "district": _clean(row.get(district_col)),
                "devices_by_field": devices_by_field,
                "all_devices": all_devices,
            }
        )
    return rows


def _trace_candidate(candidate: dict[str, str], source_rows: list[dict[str, Any]]) -> dict[str, Any]:
    device_type = _clean(candidate.get("device_type"))
    device_id = normalize_device_id(candidate.get("device_id")) or ""
    feeder = normalize_feeder(candidate.get("feeder")) or ""
    expected_field = _expected_field(device_type)
    event_count = _int(candidate.get("event_count"))

    feeder_rows = [row for row in source_rows if feeder and row["feeder"] == feeder]
    device_rows = [row for row in source_rows if device_id and device_id in row["all_devices"]]
    expected_device_rows = [
        row
        for row in source_rows
        if device_id and expected_field and device_id in row["devices_by_field"].get(expected_field, set())
    ]
    same_station_rows = [
        row
        for row in source_rows
        if feeder and row["station_prefix"] == feeder[:3] and row["is_ok"]
    ]
    same_station_feeders = Counter(row["feeder"] or "<blank>" for row in same_station_rows)
    source_status_counts_on_feeder = Counter(row["status"] or "<blank>" for row in feeder_rows)
    source_status_counts_on_device = Counter(row["status"] or "<blank>" for row in device_rows)

    expected_device_ok_rows = sum(1 for row in expected_device_rows if row["is_ok"])
    feeder_ok_rows = sum(1 for row in feeder_rows if row["is_ok"])
    feeder_no_meter_rows = sum(1 for row in feeder_rows if row["is_no_meter"])
    same_station_ok_rows = len(same_station_rows)

    result, evidence, interpretation, action = _classify_trace(
        device_id=device_id,
        feeder=feeder,
        expected_device_ok_rows=expected_device_ok_rows,
        device_rows=len(device_rows),
        feeder_rows=len(feeder_rows),
        feeder_ok_rows=feeder_ok_rows,
        feeder_no_meter_rows=feeder_no_meter_rows,
        same_station_ok_rows=same_station_ok_rows,
    )

    return {
        "priority_rank": candidate.get("priority_rank") or "",
        "device_type": device_type,
        "device_id": device_id,
        "feeder": feeder,
        "event_count": event_count,
        "upstream_trace_result": result,
        "device_rows_in_source": len(device_rows),
        "expected_device_rows_in_source": len(expected_device_rows),
        "expected_device_ok_rows": expected_device_ok_rows,
        "feeder_rows_in_source": len(feeder_rows),
        "feeder_ok_rows": feeder_ok_rows,
        "feeder_no_meter_rows": feeder_no_meter_rows,
        "same_station_ok_rows": same_station_ok_rows,
        "same_station_top_feeders": _json_counts(same_station_feeders.most_common(8)),
        "source_status_counts_on_feeder": _json_counts(source_status_counts_on_feeder.items()),
        "source_status_counts_on_device": _json_counts(source_status_counts_on_device.items()),
        "evidence_level": evidence,
        "trace_interpretation": interpretation,
        "next_action": action,
    }


def _classify_trace(
    *,
    device_id: str,
    feeder: str,
    expected_device_ok_rows: int,
    device_rows: int,
    feeder_rows: int,
    feeder_ok_rows: int,
    feeder_no_meter_rows: int,
    same_station_ok_rows: int,
) -> tuple[str, str, str, str]:
    if not device_id or not feeder:
        return (
            "cannot_trace_missing_device_or_feeder",
            "weak",
            "The Webex event did not provide enough normalized device/feeder information to trace against the upstream workbook.",
            "Review the original Webex message and add a parser pattern only if a real device id exists in the text.",
        )
    if expected_device_ok_rows:
        return (
            "source_traces_device_to_confident_ais",
            "strong",
            "The upstream workbook already traces confident AIS assets to this protection device, so runtime matching should be reviewed.",
            "Rebuild registry, rerun replay, and inspect device normalization or matching precedence.",
        )
    if device_rows:
        return (
            "source_mentions_device_but_not_as_confident_expected_level",
            "medium",
            "The device appears somewhere in the upstream workbook, but not as a confident AIS match at the expected protection level.",
            "Inspect the source trace columns for this device and decide whether registry repair or matching-rule repair is correct.",
        )
    if feeder_ok_rows:
        return (
            "source_has_confident_ais_on_feeder_but_not_device",
            "medium",
            "The feeder has confident AIS assets, but the candidate protection device is not in their upstream trace path.",
            "Use GIS/DMS topology or an updated upstream trace to decide whether the AIS assets are downstream of this device.",
        )
    if feeder_no_meter_rows:
        return (
            "source_has_only_no_meter_on_feeder",
            "weak",
            "The feeder appears only in non-confident NO_METER or incomplete trace rows.",
            "Repair the NO_METER rows before treating this feeder as a confident AIS impact match.",
        )
    if feeder_rows:
        return (
            "source_has_non_confident_rows_on_feeder",
            "weak",
            "The feeder appears in the source workbook, but no confident AIS asset is currently usable for matching.",
            "Review source row statuses and repair trace data if these are AIS pilot assets.",
        )
    if same_station_ok_rows:
        return (
            "no_source_evidence_on_candidate_feeder_same_station_has_ais",
            "source_negative",
            "The source workbook has AIS assets on other feeders from the same station prefix, but none on this candidate feeder/device.",
            "Treat as outside current traced AIS scope unless GIS/DMS topology shows AIS assets downstream of this device.",
        )
    return (
        "no_source_evidence_for_device_or_feeder",
        "source_negative",
        "The source workbook has no evidence of AIS assets on this device or feeder.",
        "Treat as outside current traced AIS scope unless a broader AIS registry or topology source says otherwise.",
    )


def _expected_field(device_type: str) -> str:
    value = (device_type or "").strip().lower()
    if value == "cb":
        return "cb"
    if value == "recloser":
        return "recloser"
    if value == "switch":
        return "switch"
    if value == "transformer":
        return "transformer"
    return ""


def _devices_from_values(*values: Any) -> tuple[str, ...]:
    devices = []
    for value in values:
        devices.extend(split_device_list(value))
    return tuple(devices)


def _pick_column(df: pd.DataFrame, candidates: tuple[str, ...], fallback_index: int | None = None) -> str:
    lowered = {str(column).strip().lower(): column for column in df.columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    if fallback_index is not None and 0 <= fallback_index < len(df.columns):
        return str(df.columns[fallback_index])
    raise ValueError(f"Could not find any of the columns: {', '.join(candidates)}")


def _first(*values: Any) -> str:
    for value in values:
        text = _clean(value)
        if text:
            return text
    return ""


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def _int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _json_counts(items: Any) -> str:
    if isinstance(items, Counter):
        pairs = items.items()
    else:
        pairs = items
    return json.dumps({str(key): int(value) for key, value in pairs}, ensure_ascii=False, sort_keys=True)


def _render_markdown(rows: list[dict[str, Any]]) -> str:
    result_counts = Counter(row["upstream_trace_result"] for row in rows)
    lines = [
        "# No-match Upstream Trace Audit",
        "",
        "This audit checks no-match Webex devices against the current traced AIS source workbook only.",
        "It does not replace a live GIS/DMS downstream trace.",
        "",
        "## Summary",
        "",
        "| Trace result | Candidates | Events |",
        "| --- | ---: | ---: |",
    ]
    for result, count in result_counts.most_common():
        events = sum(int(row["event_count"]) for row in rows if row["upstream_trace_result"] == result)
        lines.append(f"| {result} | {count} | {events} |")
    lines.extend(
        [
            "",
            "## Priority Candidates",
            "",
            "| Rank | Device | Feeder | Events | Result | Interpretation |",
            "| ---: | --- | --- | ---: | --- | --- |",
        ]
    )
    for row in sorted(rows, key=lambda item: int(item["priority_rank"] or 999999)):
        device = row["device_id"] or "<missing>"
        feeder = row["feeder"] or "<missing>"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["priority_rank"]),
                    device,
                    feeder,
                    str(row["event_count"]),
                    str(row["upstream_trace_result"]),
                    str(row["trace_interpretation"]).replace("|", "\\|"),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Reading Notes",
            "",
            "- `source_negative` means the current upstream workbook does not show AIS assets on the candidate device/feeder.",
            "- It is enough to block confident customer notification, but it is not proof from the full electrical topology.",
            "- To prove downstream impact, connect GIS/DMS topology or rerun the upstream trace for AIS assets on the candidate feeders.",
        ]
    )
    return "\n".join(lines)
