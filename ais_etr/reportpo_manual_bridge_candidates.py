from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from .reportpo_shared_key_discovery import MANUAL_BRIDGE_COLUMNS


SUGGESTION_COLUMNS = (
    "webex_message_ref",
    "reportpo_etr_event_number",
    "webex_device_id",
    "reportpo_etr_device_id",
    "feeder",
    "event_time",
    "reportpo_etr_event_start_time",
    "candidate_rank",
    "candidate_po_event_number",
    "candidate_op_device_id",
    "candidate_op_device_gis_tag",
    "candidate_feeder",
    "candidate_time_field",
    "candidate_time",
    "delta_minutes",
    "match_level",
    "score",
    "lifecycle_quality",
    "lifecycle_flags",
    "review_status",
    "decision",
    "notes",
)

LIFECYCLE_TIME_FIELDS = (
    "cr_datetime",
    "no_datetime",
    "ip_datetime",
    "last_restore_datetime",
    "cl_datetime",
)


def build_reportpo_manual_bridge_candidates(
    event_bridge_csv: str | Path,
    lifecycle_csv: str | Path,
    manual_template_csv: str | Path,
    suggestions_output: str | Path,
    template_output: str | Path,
    markdown_output: str | Path,
    pathfinding_report: str | Path | None = None,
    *,
    time_window_minutes: float = 720.0,
    top_limit: int = 5,
    min_template_score: float = 95.0,
) -> dict[str, Any]:
    focus_rows = _read_csv(event_bridge_csv)
    manual_rows = _manual_rows_by_key(manual_template_csv)
    lifecycle_rows = _load_relevant_lifecycle_rows(lifecycle_csv, focus_rows)
    suggestions_by_key, suggestion_rows = _build_suggestions(
        focus_rows,
        lifecycle_rows,
        time_window_minutes=time_window_minutes,
        top_limit=top_limit,
    )
    template_rows = _build_template_rows(
        focus_rows,
        manual_rows,
        suggestions_by_key,
        min_template_score=min_template_score,
    )
    summary = _summarize(focus_rows, suggestion_rows, template_rows, time_window_minutes, min_template_score)
    _write_csv(suggestions_output, SUGGESTION_COLUMNS, suggestion_rows)
    _write_csv(template_output, MANUAL_BRIDGE_COLUMNS, template_rows)
    output = Path(markdown_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_markdown(summary, suggestions_output, template_output), encoding="utf-8-sig")
    if pathfinding_report:
        _update_pathfinding_report(pathfinding_report, summary, markdown_output, template_output)
    return {
        **summary,
        "event_bridge_csv": str(event_bridge_csv),
        "lifecycle_csv": str(lifecycle_csv),
        "manual_template_csv": str(manual_template_csv),
        "suggestions_output": str(suggestions_output),
        "template_output": str(template_output),
        "markdown_output": str(markdown_output),
        "pathfinding_report": str(pathfinding_report) if pathfinding_report else None,
    }


def _load_relevant_lifecycle_rows(path: str | Path, focus_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    devices = set()
    feeders = set()
    for row in focus_rows:
        devices.update(_focus_devices(row))
        feeder = _norm(row.get("feeder"))
        if feeder:
            feeders.add(feeder)
    rows = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            op_device = _norm(row.get("op_device_id"))
            gis_device = _norm(row.get("op_device_gis_tag"))
            feeder = _norm(row.get("feeder"))
            if (op_device and op_device in devices) or (gis_device and gis_device in devices) or (feeder and feeder in feeders):
                rows.append(row)
    return rows


def _build_suggestions(
    focus_rows: list[dict[str, str]],
    lifecycle_rows: list[dict[str, str]],
    *,
    time_window_minutes: float,
    top_limit: int,
) -> tuple[dict[tuple[str, str], list[dict[str, str]]], list[dict[str, str]]]:
    suggestions_by_key: dict[tuple[str, str], list[dict[str, str]]] = {}
    output_rows: list[dict[str, str]] = []
    for focus in focus_rows:
        key = _manual_key(focus)
        candidates = []
        base_time = _parse_time(focus.get("event_time")) or _parse_time(focus.get("reportpo_etr_event_start_time"))
        if not base_time:
            suggestions_by_key[key] = []
            continue
        focus_devices = _focus_devices(focus)
        focus_feeder = _norm(focus.get("feeder"))
        for lifecycle in lifecycle_rows:
            candidate = _candidate_for_focus(
                focus,
                lifecycle,
                base_time=base_time,
                focus_devices=focus_devices,
                focus_feeder=focus_feeder,
                time_window_minutes=time_window_minutes,
            )
            if candidate:
                candidates.append(candidate)
        ranked = sorted(
            candidates,
            key=lambda row: (
                -_to_float(row.get("score")),
                _to_float(row.get("delta_minutes")),
                row.get("candidate_po_event_number", ""),
            ),
        )[: max(1, int(top_limit))]
        for index, row in enumerate(ranked, start=1):
            row["candidate_rank"] = str(index)
            output_rows.append(row)
        suggestions_by_key[key] = ranked
    return suggestions_by_key, output_rows


def _candidate_for_focus(
    focus: dict[str, str],
    lifecycle: dict[str, str],
    *,
    base_time: datetime,
    focus_devices: set[str],
    focus_feeder: str,
    time_window_minutes: float,
) -> dict[str, str] | None:
    event_number = str(lifecycle.get("event_number") or "").strip()
    if not event_number:
        return None
    op_device = _norm(lifecycle.get("op_device_id"))
    gis_device = _norm(lifecycle.get("op_device_gis_tag"))
    candidate_feeder = _norm(lifecycle.get("feeder"))
    device_match = bool(focus_devices.intersection({op_device, gis_device} - {""}))
    feeder_match = bool(focus_feeder and candidate_feeder and focus_feeder == candidate_feeder)
    if not (device_match or feeder_match):
        return None
    nearest = _nearest_lifecycle_time(lifecycle, base_time)
    if not nearest:
        return None
    time_field, candidate_time, delta_minutes = nearest
    if delta_minutes > time_window_minutes:
        return None
    match_level = _match_level(device_match, feeder_match)
    score = _score(match_level, delta_minutes, time_window_minutes, lifecycle.get("lifecycle_quality", ""))
    review_status, decision, notes = _candidate_decision(match_level, score, time_field)
    return {
        "webex_message_ref": focus.get("webex_message_ref", ""),
        "reportpo_etr_event_number": focus.get("reportpo_etr_event_number", ""),
        "webex_device_id": focus.get("device_id", ""),
        "reportpo_etr_device_id": focus.get("reportpo_etr_device_id", ""),
        "feeder": focus.get("feeder", ""),
        "event_time": focus.get("event_time", ""),
        "reportpo_etr_event_start_time": focus.get("reportpo_etr_event_start_time", ""),
        "candidate_rank": "",
        "candidate_po_event_number": event_number,
        "candidate_op_device_id": lifecycle.get("op_device_id", ""),
        "candidate_op_device_gis_tag": lifecycle.get("op_device_gis_tag", ""),
        "candidate_feeder": lifecycle.get("feeder", ""),
        "candidate_time_field": time_field,
        "candidate_time": candidate_time,
        "delta_minutes": _format_float(delta_minutes),
        "match_level": match_level,
        "score": _format_float(score),
        "lifecycle_quality": lifecycle.get("lifecycle_quality", ""),
        "lifecycle_flags": lifecycle.get("lifecycle_flags", ""),
        "review_status": review_status,
        "decision": decision,
        "notes": notes,
    }


def _nearest_lifecycle_time(row: dict[str, str], base_time: datetime) -> tuple[str, str, float] | None:
    nearest: tuple[str, str, float] | None = None
    for field in LIFECYCLE_TIME_FIELDS:
        parsed = _parse_time(row.get(field))
        if not parsed:
            continue
        delta = abs((parsed - base_time).total_seconds()) / 60.0
        if nearest is None or delta < nearest[2]:
            nearest = (field, str(row.get(field) or "").strip(), delta)
    return nearest


def _build_template_rows(
    focus_rows: list[dict[str, str]],
    manual_rows: dict[tuple[str, str], dict[str, str]],
    suggestions_by_key: dict[tuple[str, str], list[dict[str, str]]],
    *,
    min_template_score: float,
) -> list[dict[str, str]]:
    rows = []
    seen: set[tuple[str, str]] = set()
    for focus in focus_rows:
        key = _manual_key(focus)
        if key in seen:
            continue
        seen.add(key)
        existing = manual_rows.get(key, {})
        if str(existing.get("review_status") or "").strip().lower() == "approved":
            rows.append(_manual_row(existing))
            continue
        suggestions = suggestions_by_key.get(key, [])
        top = suggestions[0] if suggestions else {}
        if _prefill_allowed(suggestions, min_template_score):
            rows.append(
                {
                    "webex_message_ref": focus.get("webex_message_ref", ""),
                    "reportpo_etr_event_number": focus.get("reportpo_etr_event_number", ""),
                    "shared_job_id_or_ticket_id": existing.get("shared_job_id_or_ticket_id", ""),
                    "po_event_number": top.get("candidate_po_event_number", ""),
                    "review_status": "pending",
                    "reviewed_by": "",
                    "reviewed_at": "",
                    "notes": (
                        "Audit-only PO candidate suggested from device/feeder/time proximity; "
                        f"match_level={top.get('match_level', '')}; "
                        f"delta_minutes={top.get('delta_minutes', '')}; "
                        f"score={top.get('score', '')}."
                    ),
                }
            )
            continue
        rows.append(
            {
                "webex_message_ref": focus.get("webex_message_ref", ""),
                "reportpo_etr_event_number": focus.get("reportpo_etr_event_number", ""),
                "shared_job_id_or_ticket_id": existing.get("shared_job_id_or_ticket_id", ""),
                "po_event_number": existing.get("po_event_number", ""),
                "review_status": existing.get("review_status", "pending") or "pending",
                "reviewed_by": existing.get("reviewed_by", ""),
                "reviewed_at": existing.get("reviewed_at", ""),
                "notes": _template_note(top, suggestions, min_template_score),
            }
        )
    for key, existing in manual_rows.items():
        if key not in seen:
            rows.append(_manual_row(existing))
    return rows


def _prefill_allowed(suggestions: list[dict[str, str]], min_template_score: float) -> bool:
    if not suggestions:
        return False
    top = suggestions[0]
    if top.get("candidate_time_field") == "cl_datetime":
        return False
    if top.get("match_level") != "device_feeder_time":
        return False
    if _to_float(top.get("score")) < min_template_score:
        return False
    if len(suggestions) >= 2:
        second = suggestions[1]
        if top.get("candidate_po_event_number") != second.get("candidate_po_event_number") and abs(
            _to_float(top.get("score")) - _to_float(second.get("score"))
        ) < 3.0:
            return False
    return True


def _template_note(top: dict[str, str], suggestions: list[dict[str, str]], min_template_score: float) -> str:
    if not suggestions:
        return "No PO lifecycle candidate found inside the configured time window."
    if top.get("candidate_time_field") == "cl_datetime":
        return "Candidate is nearest to administrative close time; do not use without stronger lifecycle evidence."
    if top.get("match_level") != "device_feeder_time":
        return "Candidate exists but is context-only; do not use without manual evidence."
    if _to_float(top.get("score")) < min_template_score:
        return f"Candidate exists but score is below pending-template threshold {min_template_score:g}."
    return "Candidate is ambiguous; inspect suggestion audit before approval."


def _summarize(
    focus_rows: list[dict[str, str]],
    suggestion_rows: list[dict[str, str]],
    template_rows: list[dict[str, str]],
    time_window_minutes: float,
    min_template_score: float,
) -> dict[str, Any]:
    top_by_key = {}
    for row in suggestion_rows:
        if row.get("candidate_rank") == "1":
            top_by_key[(row.get("webex_message_ref", ""), row.get("reportpo_etr_event_number", ""))] = row
    top_levels = Counter(row.get("match_level") or "<blank>" for row in top_by_key.values())
    template_status = Counter(row.get("review_status") or "<blank>" for row in template_rows)
    prefilled = sum(1 for row in template_rows if str(row.get("po_event_number") or "").strip() and row.get("review_status") == "pending")
    approved = sum(1 for row in template_rows if str(row.get("review_status") or "").strip().lower() == "approved")
    return {
        "focus_rows": len(focus_rows),
        "suggestion_rows": len(suggestion_rows),
        "events_with_any_candidate": len(top_by_key),
        "events_without_candidate": max(0, len({_manual_key(row) for row in focus_rows}) - len(top_by_key)),
        "top_match_level_counts": dict(top_levels.most_common()),
        "pending_template_prefills": prefilled,
        "approved_rows_preserved": approved,
        "template_status_counts": dict(template_status.most_common()),
        "time_window_minutes": time_window_minutes,
        "min_template_score": min_template_score,
        "decision": "manual_review_required",
        "recommended_next": "Review pending PO candidates against source screens or owner evidence, then mark only verified rows as approved.",
    }


def _render_markdown(summary: dict[str, Any], suggestions_output: str | Path, template_output: str | Path) -> str:
    lines = [
        "# ReportPO Manual Bridge Candidate Suggestions",
        "",
        "Purpose: propose audit-only PO lifecycle candidates for manual bridge review using device, feeder, and timestamp proximity. These suggestions do not fill truth and do not train a model.",
        "",
        "## Summary",
        "",
        f"- Focus rows: {summary['focus_rows']}",
        f"- Suggestion rows: {summary['suggestion_rows']}",
        f"- Events with any candidate: {summary['events_with_any_candidate']}",
        f"- Events without candidate: {summary['events_without_candidate']}",
        f"- Pending template pre-fills: {summary['pending_template_prefills']}",
        f"- Approved rows preserved: {summary['approved_rows_preserved']}",
        f"- Time window minutes: {summary['time_window_minutes']}",
        f"- Minimum template score: {summary['min_template_score']}",
        "",
        "## Top Match Levels",
        "",
        "| Match level | Events |",
        "| --- | ---: |",
    ]
    for level, count in summary["top_match_level_counts"].items():
        lines.append(f"| {level} | {count} |")
    lines.extend(["", "## Template Status", "", "| Status | Rows |", "| --- | ---: |"])
    for status, count in summary["template_status_counts"].items():
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
            "",
            "## Outputs",
            "",
            f"- Candidate audit: `{suggestions_output}`",
            f"- Review template: `{template_output}`",
            "",
            "## Decision",
            "",
            "- This remains manual review evidence only.",
            "- Use only rows changed to `approved` for any future lifecycle bridge audit.",
            "- Feeder-only or ambiguous candidates must not be used as automatic truth.",
            "",
            "## Safety Notes",
            "",
            "- Outputs include event references, device context, feeder context, and ReportPO event identifiers needed for review.",
            "- Outputs exclude source chat bodies, space identifiers, credential values, meter-id lists, and unnecessary customer identity fields.",
        ]
    )
    return "\n".join(lines) + "\n"


def _update_pathfinding_report(
    path: str | Path,
    summary: dict[str, Any],
    markdown_output: str | Path,
    template_output: str | Path,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = output.read_text(encoding="utf-8-sig") if output.exists() else "# AIS ETR Model Pathfinding Next Report\n"
    start = "<!-- reportpo-manual-bridge-candidates:start -->"
    end = "<!-- reportpo-manual-bridge-candidates:end -->"
    section = "\n".join(
        [
            start,
            "",
            "## ReportPO Manual Bridge Candidate Suggestions",
            "",
            f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
            f"- Focus rows: {summary['focus_rows']}",
            f"- Events with any candidate: {summary['events_with_any_candidate']}",
            f"- Pending template pre-fills: {summary['pending_template_prefills']}",
            f"- Full report: `{markdown_output}`",
            f"- Review template: `{template_output}`",
            f"- Next action: {summary['recommended_next']}",
            "",
            "Production customer send and model promotion remain blocked until reviewed bridge rows and sustained-outage gates pass.",
            "",
            end,
        ]
    ) + "\n"
    if start in existing and end in existing:
        prefix = existing.split(start, 1)[0].rstrip()
        suffix = existing.split(end, 1)[1].lstrip()
        text = f"{prefix}\n\n{section}"
        if suffix:
            text += "\n" + suffix
    else:
        text = existing.rstrip() + "\n\n" + section
    output.write_text(text, encoding="utf-8-sig")


def _match_level(device_match: bool, feeder_match: bool) -> str:
    if device_match and feeder_match:
        return "device_feeder_time"
    if device_match:
        return "device_time"
    return "feeder_time_audit_only"


def _score(match_level: str, delta_minutes: float, time_window_minutes: float, lifecycle_quality: str) -> float:
    base = {
        "device_feeder_time": 100.0,
        "device_time": 82.0,
        "feeder_time_audit_only": 45.0,
    }.get(match_level, 0.0)
    time_bonus = max(0.0, 20.0 * (1.0 - min(delta_minutes, time_window_minutes) / max(time_window_minutes, 1.0)))
    penalty = 8.0 if str(lifecycle_quality or "").strip().lower() in {"invalid_sequence", "missing_restore"} else 0.0
    return max(0.0, base + time_bonus - penalty)


def _candidate_decision(match_level: str, score: float, time_field: str) -> tuple[str, str, str]:
    if time_field == "cl_datetime":
        return (
            "audit_only",
            "admin_close_time_review",
            "Nearest lifecycle timestamp is administrative close time, not customer restoration evidence.",
        )
    if match_level == "feeder_time_audit_only":
        return "audit_only", "feeder_only_review", "Feeder-time proximity is broad; owner/manual validation required."
    if score >= 95:
        return "pending", "candidate_pending_review", "Strong proximity candidate; still requires manual approval before use."
    return "audit_only", "low_score_review", "Candidate exists but score is below the pending-template threshold."


def _focus_devices(row: dict[str, str]) -> set[str]:
    return {value for value in {_norm(row.get("device_id")), _norm(row.get("reportpo_etr_device_id"))} if value}


def _manual_rows_by_key(path: str | Path) -> dict[tuple[str, str], dict[str, str]]:
    output = {}
    for row in _read_csv(path):
        output[_manual_key(row)] = _manual_row(row)
    return output


def _manual_key(row: dict[str, str]) -> tuple[str, str]:
    return (str(row.get("webex_message_ref") or "").strip(), str(row.get("reportpo_etr_event_number") or "").strip())


def _manual_row(row: dict[str, str]) -> dict[str, str]:
    return {column: row.get(column, "") for column in MANUAL_BRIDGE_COLUMNS}


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = text.replace("T", " ").replace("Z", "")
    if "+" in cleaned:
        cleaned = cleaned.split("+", 1)[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    if not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: str | Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def _to_float(value: Any) -> float:
    try:
        return float(str(value or "0").strip())
    except ValueError:
        return 0.0


def _format_float(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")
