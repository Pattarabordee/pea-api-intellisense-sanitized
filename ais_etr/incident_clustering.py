from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
import sqlite3
from typing import Any

from .truth_quality import GATE_COVERAGE_MAX, GATE_COVERAGE_MIN, GATE_Q50_MAE_MAX


INCIDENT_COLUMNS = (
    "event_id",
    "webex_message_ref",
    "incident_id",
    "event_count",
    "event_time",
    "last_event_time",
    "event_span_minutes",
    "district",
    "device_type",
    "device_id",
    "feeder",
    "match_level",
    "match_confidence",
    "affected_count",
    "actual_restoration_minutes",
    "truth_source",
    "truth_cluster_id",
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
    "cluster_notes",
)

REPLAY_COLUMNS = (
    "segment",
    "grain",
    "rows",
    "source_webex_events",
    "incidents",
    "compressed_events",
    "q50_mae_minutes",
    "q10_q90_coverage",
    "high_error_rows",
    "mean_actual_minutes",
    "mean_p50_minutes",
    "median_absolute_error_minutes",
    "max_absolute_error_minutes",
    "gate_status",
    "notes",
)


@dataclass(frozen=True)
class IncidentSummary:
    source_events: int
    source_events_with_truth: int
    incidents: int
    compressed_events: int
    current_q50_mae_minutes: float | None
    current_q10_q90_coverage: float | None
    challenger_q50_mae_minutes: float | None
    challenger_q10_q90_coverage: float | None
    gate_status: str


def build_shadow_incident_replay_report(
    db_path: str | Path,
    comparison_csv: str | Path,
    audit_csv: str | Path,
    incident_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    high_error_minutes: float = 60.0,
    focus_feeders: tuple[str, ...] = ("SEK06",),
    focus_devices: tuple[str, ...] = ("SEK06VR-103", "SEK06VR-104", "SEK06VR-105"),
) -> dict[str, Any]:
    """Compare raw Webex-message evaluation with AIS incident-level evaluation."""

    raw_rows = _raw_rows_with_incident_ids(db_path, comparison_csv, audit_csv)
    incident_rows = _read_csv(incident_csv)
    incident_by_id = {row.get("incident_id", ""): row for row in incident_rows if row.get("incident_id")}
    raw_rows = [
        {**row, "_incident_event_count": incident_by_id.get(row.get("_incident_id", ""), {}).get("event_count", "1")}
        for row in raw_rows
    ]
    segment_specs = _replay_segment_specs(raw_rows, incident_rows, focus_feeders, focus_devices)
    rows: list[dict[str, str]] = []
    for segment in segment_specs:
        rows.append(
            _replay_metric_row(
                segment["name"],
                "raw_webex_events",
                segment["raw_rows"],
                high_error_minutes,
                notes=segment["notes"],
            )
        )
        rows.append(
            _replay_metric_row(
                segment["name"],
                "clustered_incidents",
                segment["incident_rows"],
                high_error_minutes,
                notes=segment["notes"],
            )
        )
    _write_csv(output_csv, REPLAY_COLUMNS, rows)
    summary = _replay_summary(rows, raw_rows, incident_rows)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_replay_markdown(summary, rows), encoding="utf-8-sig")
    return {
        **summary,
        "db_path": str(db_path),
        "comparison_csv": str(comparison_csv),
        "audit_csv": str(audit_csv),
        "incident_csv": str(incident_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "high_error_minutes": high_error_minutes,
        "focus_feeders": list(focus_feeders),
        "focus_devices": list(focus_devices),
    }


def build_shadow_incident_clusters(
    db_path: str | Path,
    comparison_csv: str | Path,
    audit_csv: str | Path,
    output_csv: str | Path,
    markdown_output: str | Path | None = None,
    *,
    prediction_policy: str = "first_event",
) -> dict[str, Any]:
    if prediction_policy != "first_event":
        raise ValueError("prediction_policy currently supports only 'first_event'")

    comparison_rows = _read_csv(comparison_csv)
    audit_by_message = _load_audit_by_message(audit_csv)
    message_by_event = _load_message_by_event(db_path)

    enriched: list[dict[str, str]] = []
    for row in comparison_rows:
        actual = _to_float(row.get("actual_restoration_minutes"))
        if actual is None:
            continue
        message_id = message_by_event.get(row.get("event_id") or "")
        audit = audit_by_message.get(message_id or "", {})
        cluster_id = _extract_truth_cluster_id(audit.get("truth_notes") or "")
        if not cluster_id:
            cluster_id = f"event-{row.get('event_id') or row.get('webex_message_ref') or len(enriched)}"
        enriched.append({**row, "_message_id": message_id or "", "_truth_cluster_id": cluster_id})

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in enriched:
        grouped.setdefault(row["_truth_cluster_id"], []).append(row)

    incident_rows = [
        _incident_row(cluster_id, rows, prediction_policy=prediction_policy)
        for cluster_id, rows in sorted(grouped.items(), key=lambda item: _cluster_sort_key(item[1]))
    ]
    _write_csv(output_csv, INCIDENT_COLUMNS, incident_rows)

    summary = _summary(comparison_rows, enriched, incident_rows)
    if markdown_output:
        output = Path(markdown_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_render_markdown(summary, incident_rows), encoding="utf-8-sig")

    return {
        "db_path": str(db_path),
        "comparison_csv": str(comparison_csv),
        "audit_csv": str(audit_csv),
        "output_csv": str(output_csv),
        "markdown_output": str(markdown_output) if markdown_output else None,
        "prediction_policy": prediction_policy,
        "source_events": summary.source_events,
        "source_events_with_truth": summary.source_events_with_truth,
        "incidents": summary.incidents,
        "compressed_events": summary.compressed_events,
        "current_q50_mae_minutes": summary.current_q50_mae_minutes,
        "current_q10_q90_coverage": summary.current_q10_q90_coverage,
        "challenger_q50_mae_minutes": summary.challenger_q50_mae_minutes,
        "challenger_q10_q90_coverage": summary.challenger_q10_q90_coverage,
        "gate_status": summary.gate_status,
    }


def _raw_rows_with_incident_ids(
    db_path: str | Path,
    comparison_csv: str | Path,
    audit_csv: str | Path,
) -> list[dict[str, str]]:
    comparison_rows = [row for row in _read_csv(comparison_csv) if _to_float(row.get("actual_restoration_minutes")) is not None]
    audit_by_message = _load_audit_by_message(audit_csv)
    message_by_event = _load_message_by_event(db_path)
    rows = []
    for index, row in enumerate(comparison_rows):
        message_id = message_by_event.get(row.get("event_id") or "", "")
        audit = audit_by_message.get(message_id, {})
        incident_id = _extract_truth_cluster_id(audit.get("truth_notes") or "")
        if not incident_id:
            incident_id = f"event-{row.get('event_id') or row.get('webex_message_ref') or index}"
        rows.append({**row, "_incident_id": incident_id})
    return rows


def _replay_segment_specs(
    raw_rows: list[dict[str, str]],
    incident_rows: list[dict[str, str]],
    focus_feeders: tuple[str, ...],
    focus_devices: tuple[str, ...],
) -> list[dict[str, Any]]:
    incident_by_id = {row.get("incident_id", ""): row for row in incident_rows if row.get("incident_id")}
    specs: list[dict[str, Any]] = [
        {
            "name": "all_truth",
            "raw_rows": raw_rows,
            "incident_rows": incident_rows,
            "notes": "All AIS truth-matched shadow rows.",
        },
        {
            "name": "repeated_incidents",
            "raw_rows": [row for row in raw_rows if _to_int(row.get("_incident_event_count")) >= 2],
            "incident_rows": [row for row in incident_rows if _to_int(row.get("event_count")) >= 2],
            "notes": "Only AIS incidents represented by two or more Webex events.",
        },
        {
            "name": "single_event_incidents",
            "raw_rows": [row for row in raw_rows if _to_int(row.get("_incident_event_count")) <= 1],
            "incident_rows": [row for row in incident_rows if _to_int(row.get("event_count")) <= 1],
            "notes": "AIS incidents represented by exactly one Webex event.",
        },
    ]
    feeder_set = set(str(value or "").strip().upper() for value in focus_feeders if str(value or "").strip())
    feeder_set.update(_top_values_by_error(raw_rows, "feeder", limit=5))
    for feeder in sorted(feeder_set):
        raw_segment = [row for row in raw_rows if str(row.get("feeder") or "").strip().upper() == feeder]
        specs.append(
            {
                "name": f"feeder:{feeder}",
                "raw_rows": raw_segment,
                "incident_rows": _incident_rows_touched_by_raw_segment(raw_segment, incident_by_id),
                "notes": "Feeder-focused incident replay segment; incident rows include incidents touched by this feeder.",
            }
        )
    device_set = set(str(value or "").strip().upper() for value in focus_devices if str(value or "").strip())
    device_set.update(_top_values_by_error(raw_rows, "device_id", limit=5))
    for device in sorted(device_set):
        raw_segment = [row for row in raw_rows if str(row.get("device_id") or "").strip().upper() == device]
        specs.append(
            {
                "name": f"device:{device}",
                "raw_rows": raw_segment,
                "incident_rows": _incident_rows_touched_by_raw_segment(raw_segment, incident_by_id),
                "notes": "Device-focused incident replay segment; incident rows include incidents touched by this device.",
            }
        )
    return specs


def _incident_rows_touched_by_raw_segment(
    raw_segment: list[dict[str, str]],
    incident_by_id: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    incident_ids = []
    seen = set()
    for row in raw_segment:
        incident_id = row.get("_incident_id", "")
        if incident_id and incident_id not in seen:
            incident_ids.append(incident_id)
            seen.add(incident_id)
    return [incident_by_id[incident_id] for incident_id in incident_ids if incident_id in incident_by_id]


def _replay_metric_row(
    segment: str,
    grain: str,
    rows: list[dict[str, str]],
    high_error_minutes: float,
    *,
    notes: str,
) -> dict[str, str]:
    errors = _numbers(rows, "current_absolute_error")
    actuals = _numbers(rows, "actual_restoration_minutes")
    p50s = _numbers(rows, "current_p50")
    incident_ids = {row.get("_incident_id") or row.get("incident_id") or row.get("event_id") for row in rows}
    source_events = sum(_to_int(row.get("event_count")) or 1 for row in rows) if grain == "clustered_incidents" else len(rows)
    incidents = len(rows) if grain == "clustered_incidents" else len({value for value in incident_ids if value})
    compressed = max(0, source_events - incidents)
    return {
        "segment": segment,
        "grain": grain,
        "rows": str(len(rows)),
        "source_webex_events": str(source_events),
        "incidents": str(incidents),
        "compressed_events": str(compressed),
        "q50_mae_minutes": _fmt(_mean(errors)),
        "q10_q90_coverage": _fmt(_coverage(rows, "current_covered_q10_q90"), digits=3),
        "high_error_rows": str(sum(1 for error in errors if error >= high_error_minutes)),
        "mean_actual_minutes": _fmt(_mean(actuals)),
        "mean_p50_minutes": _fmt(_mean(p50s)),
        "median_absolute_error_minutes": _fmt(_median(errors)),
        "max_absolute_error_minutes": _fmt(max(errors) if errors else None),
        "gate_status": _gate_status(_mean(errors), _coverage(rows, "current_covered_q10_q90")),
        "notes": notes,
    }


def _replay_summary(
    rows: list[dict[str, str]],
    raw_rows: list[dict[str, str]],
    incident_rows: list[dict[str, str]],
) -> dict[str, Any]:
    all_raw = _find_metric(rows, "all_truth", "raw_webex_events")
    all_incident = _find_metric(rows, "all_truth", "clustered_incidents")
    repeated_raw = _find_metric(rows, "repeated_incidents", "raw_webex_events")
    repeated_incident = _find_metric(rows, "repeated_incidents", "clustered_incidents")
    raw_mae = _to_float(all_raw.get("q50_mae_minutes"))
    incident_mae = _to_float(all_incident.get("q50_mae_minutes"))
    repeated_raw_mae = _to_float(repeated_raw.get("q50_mae_minutes"))
    repeated_incident_mae = _to_float(repeated_incident.get("q50_mae_minutes"))
    return {
        "raw_webex_events_with_truth": len(raw_rows),
        "clustered_incidents": len(incident_rows),
        "compressed_events": max(0, len(raw_rows) - len(incident_rows)),
        "raw_q50_mae_minutes": raw_mae,
        "incident_q50_mae_minutes": incident_mae,
        "incident_minus_raw_mae_minutes": _delta(incident_mae, raw_mae),
        "raw_q10_q90_coverage": _to_float(all_raw.get("q10_q90_coverage")),
        "incident_q10_q90_coverage": _to_float(all_incident.get("q10_q90_coverage")),
        "repeated_raw_q50_mae_minutes": repeated_raw_mae,
        "repeated_incident_q50_mae_minutes": repeated_incident_mae,
        "repeated_incident_minus_raw_mae_minutes": _delta(repeated_incident_mae, repeated_raw_mae),
        "recommendation": _replay_recommendation(raw_mae, incident_mae, repeated_raw_mae, repeated_incident_mae),
    }


def _render_replay_markdown(summary: dict[str, Any], rows: list[dict[str, str]]) -> str:
    key_segments = [
        row
        for row in rows
        if row.get("segment") in {"all_truth", "repeated_incidents", "single_event_incidents", "feeder:SEK06"}
    ]
    top_segments = sorted(
        [row for row in rows if row.get("grain") == "clustered_incidents"],
        key=lambda row: (_to_float(row.get("q50_mae_minutes")) or 0, _to_int(row.get("high_error_rows"))),
        reverse=True,
    )[:8]
    lines = [
        "# AIS Shadow Incident Replay Report",
        "",
        "This report compares message-level shadow evaluation with AIS incident-level evaluation. It is shadow-only and does not change notifications or model artifacts.",
        "",
        "## Summary",
        "",
        f"- Message rows with AIS truth: {summary['raw_webex_events_with_truth']}",
        f"- Clustered AIS incidents: {summary['clustered_incidents']}",
        f"- Compressed Webex rows: {summary['compressed_events']}",
        f"- Raw q50 MAE: {_blank(summary['raw_q50_mae_minutes'])} min",
        f"- Incident q50 MAE: {_blank(summary['incident_q50_mae_minutes'])} min",
        f"- Incident minus raw MAE: {_blank(summary['incident_minus_raw_mae_minutes'])} min",
        f"- Raw q10-q90 coverage: {_blank(summary['raw_q10_q90_coverage'])}",
        f"- Incident q10-q90 coverage: {_blank(summary['incident_q10_q90_coverage'])}",
        "",
        "## Key Segments",
        "",
        "| Segment | Grain | Rows | Source Webex | Incidents | MAE | Coverage | High-error |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in key_segments:
        lines.append(
            "| {segment} | {grain} | {rows} | {source} | {incidents} | {mae} | {coverage} | {high} |".format(
                segment=row["segment"],
                grain=row["grain"],
                rows=row["rows"],
                source=row["source_webex_events"],
                incidents=row["incidents"],
                mae=row["q50_mae_minutes"],
                coverage=row["q10_q90_coverage"],
                high=row["high_error_rows"],
            )
        )
    lines.extend(
        [
            "",
            "## Highest Incident-Level Error Segments",
            "",
            "| Segment | Incidents | Source Webex | MAE | Coverage | High-error |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in top_segments:
        lines.append(
            "| {segment} | {incidents} | {source} | {mae} | {coverage} | {high} |".format(
                segment=row["segment"],
                incidents=row["incidents"],
                source=row["source_webex_events"],
                mae=row["q50_mae_minutes"],
                coverage=row["q10_q90_coverage"],
                high=row["high_error_rows"],
            )
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            str(summary["recommendation"]),
            "",
        "## Safety Notes",
        "",
        "- Outputs are aggregate replay metrics only.",
        "- Outputs omit full message ids, source chat bodies, room identifiers, credential values, meter identifier lists, and customer identity fields.",
    ]
    )
    return "\n".join(lines) + "\n"


def _replay_recommendation(
    raw_mae: float | None,
    incident_mae: float | None,
    repeated_raw_mae: float | None,
    repeated_incident_mae: float | None,
) -> str:
    if raw_mae is None or incident_mae is None:
        return "Insufficient AIS truth for incident replay; continue shadow capture."
    if repeated_raw_mae is not None and repeated_incident_mae is not None and repeated_incident_mae > repeated_raw_mae:
        return "Keep incident-level evaluation as the customer-facing gate, but build notification-time remaining-ETR features because first-event predictions are worse than later duplicate Webex rows."
    if incident_mae <= raw_mae:
        return "Incident clustering reduces apparent error; use incident-level metrics before model tuning."
    return "Incident clustering removes duplicate evidence but MAE remains high; prioritize AIS active-state and remaining-restoration features before tuning the baseline model."


def _incident_row(cluster_id: str, rows: list[dict[str, str]], *, prediction_policy: str) -> dict[str, str]:
    sorted_rows = sorted(rows, key=lambda row: (_parse_dt(row.get("event_time")) or datetime.max, row.get("event_id") or ""))
    selected = sorted_rows[0]
    actual_values = [_to_float(row.get("actual_restoration_minutes")) for row in rows]
    actual = max(value for value in actual_values if value is not None)
    current_p50 = _to_float(selected.get("current_p50"))
    current_q10 = _to_float(selected.get("current_q10"))
    current_q90 = _to_float(selected.get("current_q90"))
    challenger_p50 = _to_float(selected.get("challenger_p50"))
    challenger_q10 = _to_float(selected.get("challenger_q10"))
    challenger_q90 = _to_float(selected.get("challenger_q90"))
    current_error = abs(current_p50 - actual) if current_p50 is not None else None
    challenger_error = abs(challenger_p50 - actual) if challenger_p50 is not None else None
    first_dt = _parse_dt(sorted_rows[0].get("event_time"))
    last_dt = _parse_dt(sorted_rows[-1].get("event_time"))
    span = None
    if first_dt and last_dt:
        span = round((last_dt - first_dt).total_seconds() / 60, 2)
    affected_counts = [_to_float(row.get("affected_count")) for row in rows]
    affected_max = max([int(value) for value in affected_counts if value is not None] or [0])
    device_types = _unique_values(rows, "device_type")
    feeders = _unique_values(rows, "feeder")
    match_levels = _unique_values(rows, "match_level")
    districts = _unique_values(rows, "district")
    cluster_notes = (
        f"prediction_policy={prediction_policy}; source_webex_events={len(rows)}; "
        f"device_ids={len(_unique_values(rows, 'device_id'))}; feeders={len(feeders)}"
    )
    return {
        **{column: "" for column in INCIDENT_COLUMNS},
        "event_id": selected.get("event_id", ""),
        "webex_message_ref": selected.get("webex_message_ref", ""),
        "incident_id": cluster_id,
        "event_count": str(len(rows)),
        "event_time": selected.get("event_time", ""),
        "last_event_time": sorted_rows[-1].get("event_time", ""),
        "event_span_minutes": _fmt(span),
        "district": _join_limited(districts),
        "device_type": _join_limited(device_types),
        "device_id": selected.get("device_id", ""),
        "feeder": _join_limited(feeders),
        "match_level": _join_limited(match_levels),
        "match_confidence": selected.get("match_confidence", ""),
        "affected_count": str(affected_max),
        "actual_restoration_minutes": _fmt(actual),
        "truth_source": selected.get("truth_source", ""),
        "truth_cluster_id": cluster_id,
        "current_model_version": selected.get("current_model_version", ""),
        "current_p50": selected.get("current_p50", ""),
        "current_q10": selected.get("current_q10", ""),
        "current_q90": selected.get("current_q90", ""),
        "current_risk_level": selected.get("current_risk_level", ""),
        "current_absolute_error": _fmt(current_error),
        "current_covered_q10_q90": _bool_str(_covered(actual, current_q10, current_q90)),
        "challenger_model_version": selected.get("challenger_model_version", ""),
        "challenger_p50": selected.get("challenger_p50", ""),
        "challenger_q10": selected.get("challenger_q10", ""),
        "challenger_q90": selected.get("challenger_q90", ""),
        "challenger_risk_level": selected.get("challenger_risk_level", ""),
        "challenger_absolute_error": _fmt(challenger_error),
        "challenger_covered_q10_q90": _bool_str(_covered(actual, challenger_q10, challenger_q90)),
        "p50_delta_challenger_minus_current": _fmt(_delta(challenger_p50, current_p50)),
        "absolute_error_delta_challenger_minus_current": _fmt(_delta(challenger_error, current_error)),
        "cluster_notes": cluster_notes,
    }


def _summary(
    comparison_rows: list[dict[str, str]],
    enriched_rows: list[dict[str, str]],
    incident_rows: list[dict[str, str]],
) -> IncidentSummary:
    current_errors = _numbers(incident_rows, "current_absolute_error")
    challenger_errors = _numbers(incident_rows, "challenger_absolute_error")
    current_coverage = _coverage(incident_rows, "current_covered_q10_q90")
    challenger_coverage = _coverage(incident_rows, "challenger_covered_q10_q90")
    current_mae = _round_or_none(_mean(current_errors))
    challenger_mae = _round_or_none(_mean(challenger_errors))
    gate_status = _gate_status(current_mae, current_coverage)
    return IncidentSummary(
        source_events=len(comparison_rows),
        source_events_with_truth=len(enriched_rows),
        incidents=len(incident_rows),
        compressed_events=len(enriched_rows) - len(incident_rows),
        current_q50_mae_minutes=current_mae,
        current_q10_q90_coverage=_round_or_none(current_coverage, digits=3),
        challenger_q50_mae_minutes=challenger_mae,
        challenger_q10_q90_coverage=_round_or_none(challenger_coverage, digits=3),
        gate_status=gate_status,
    )


def _render_markdown(summary: IncidentSummary, rows: list[dict[str, str]]) -> str:
    event_count_dist = Counter(row.get("event_count") or "0" for row in rows)
    lines = [
        "# AIS Shadow Incident Clustering",
        "",
        "This report deduplicates Webex shadow events that map to the same AIS outage interval. It evaluates the first Webex prediction per incident and does not expose PEANO lists or raw Webex text.",
        "",
        "## Summary",
        "",
        f"- Source Webex comparison rows: {summary.source_events}",
        f"- Source rows with AIS truth: {summary.source_events_with_truth}",
        f"- Incident clusters: {summary.incidents}",
        f"- Compressed duplicate truth rows: {summary.compressed_events}",
        f"- Current q50 MAE: {_blank(summary.current_q50_mae_minutes)} min",
        f"- Current q10-q90 coverage: {_blank(summary.current_q10_q90_coverage)}",
        f"- Gate status: {summary.gate_status}",
        "",
        "## Event Count Per Incident",
        "",
        "| Webex events in incident | Incidents |",
        "| ---: | ---: |",
    ]
    for count, total in sorted(event_count_dist.items(), key=lambda item: int(item[0])):
        lines.append(f"| {count} | {total} |")
    lines.extend(
        [
            "",
            "## Top Incident Errors",
            "",
            "| Incident | Events | First event time | Feeder | Actual min | Current p50 | Error |",
            "| --- | ---: | --- | --- | ---: | ---: | ---: |",
        ]
    )
    top = sorted(rows, key=lambda row: _to_float(row.get("current_absolute_error")) or 0, reverse=True)[:10]
    for row in top:
        lines.append(
            "| {incident} | {events} | {time} | {feeder} | {actual} | {p50} | {err} |".format(
                incident=row.get("incident_id", ""),
                events=row.get("event_count", ""),
                time=row.get("event_time", ""),
                feeder=row.get("feeder", ""),
                actual=row.get("actual_restoration_minutes", ""),
                p50=row.get("current_p50", ""),
                err=row.get("current_absolute_error", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Incident-level evaluation is safer for model decisions than raw Webex-message-level evaluation when repeated Webex messages map to one AIS outage interval.",
            "- If incident-level MAE remains high after clustering, the next bottleneck is model target/features rather than duplicate message counting alone.",
            "- Production AIS send remains blocked until sustained incident-level gate passes and source-owner validation is complete.",
        ]
    )
    return "\n".join(lines) + "\n"


def _load_message_by_event(db_path: str | Path) -> dict[str, str]:
    path = Path(db_path)
    if not path.exists():
        return {}
    uri = "file:" + str(path.resolve()).replace("\\", "/") + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        return {
            str(event_id): str(message_id or "")
            for event_id, message_id in conn.execute(
                "SELECT event_id, webex_message_id FROM outage_events WHERE event_id IS NOT NULL"
            ).fetchall()
        }
    finally:
        conn.close()


def _load_audit_by_message(path: str | Path) -> dict[str, dict[str, str]]:
    rows = _read_csv(path)
    return {row.get("webex_message_id", ""): row for row in rows if row.get("webex_message_id")}


def _extract_truth_cluster_id(notes: str) -> str:
    match = re.search(r"(?:^|;\s*)truth_cluster_id=([^;]+)", notes or "")
    return match.group(1).strip() if match else ""


def _cluster_sort_key(rows: list[dict[str, str]]) -> tuple[datetime, str]:
    first = min((_parse_dt(row.get("event_time")) or datetime.max for row in rows), default=datetime.max)
    return first, rows[0].get("_truth_cluster_id") or ""


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: str | Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _numbers(rows: list[dict[str, str]], column: str) -> list[float]:
    return [value for value in (_to_float(row.get(column)) for row in rows) if value is not None]


def _coverage(rows: list[dict[str, str]], column: str) -> float | None:
    values = [str(row.get(column) or "").upper() for row in rows if str(row.get(column) or "").strip()]
    if not values:
        return None
    return sum(1 for value in values if value == "TRUE") / len(values)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round_or_none(value: float | None, *, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _gate_status(mae: float | None, coverage: float | None) -> str:
    if mae is None or coverage is None:
        return "no_truth"
    if mae <= GATE_Q50_MAE_MAX and GATE_COVERAGE_MIN <= coverage <= GATE_COVERAGE_MAX:
        return "pass"
    return "fail"


def _unique_values(rows: list[dict[str, str]], column: str) -> list[str]:
    return sorted({str(row.get(column) or "").strip() for row in rows if str(row.get(column) or "").strip()})


def _top_values_by_error(rows: list[dict[str, str]], column: str, *, limit: int) -> set[str]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        value = str(row.get(column) or "").strip().upper()
        error = _to_float(row.get("current_absolute_error"))
        if not value or error is None:
            continue
        grouped.setdefault(value, []).append(error)
    ranked = sorted(grouped.items(), key=lambda item: (sum(item[1]) / len(item[1]), len(item[1])), reverse=True)
    return {value for value, _ in ranked[:limit]}


def _join_limited(values: list[str], limit: int = 3) -> str:
    if len(values) <= limit:
        return "|".join(values)
    return "|".join(values[:limit]) + f"|+{len(values) - limit}"


def _covered(actual: float, q10: float | None, q90: float | None) -> bool | None:
    if q10 is None or q90 is None:
        return None
    return q10 <= actual <= q90


def _bool_str(value: bool | None) -> str:
    if value is None:
        return ""
    return "TRUE" if value else "FALSE"


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").strip()))
    except ValueError:
        return 0


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[midpoint]
    return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2


def _find_metric(rows: list[dict[str, str]], segment: str, grain: str) -> dict[str, str]:
    return next((row for row in rows if row.get("segment") == segment and row.get("grain") == grain), {})


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _fmt(value: float | None, *, digits: int = 2) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}".rstrip("0").rstrip(".") if not float(value).is_integer() else f"{value:.1f}"


def _blank(value: Any) -> str:
    return "" if value is None else str(value)
