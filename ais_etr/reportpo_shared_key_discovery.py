from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime
from pathlib import Path
from typing import Any


CANDIDATE_COLUMNS = (
    "candidate_id",
    "entity",
    "property",
    "canonical_side",
    "canonical_column",
    "category",
    "key_hint",
    "key_strength",
    "role",
    "data_type_label",
    "visual_count",
    "visual_ids",
    "available_in_canonical",
    "non_empty_values",
    "unique_values",
    "duplicate_values",
    "focus_values",
    "source_evidence",
    "notes",
)

OVERLAP_COLUMNS = (
    "left_side",
    "left_entity",
    "left_field",
    "right_side",
    "right_entity",
    "right_field",
    "join_purpose",
    "key_strength",
    "status",
    "left_non_empty",
    "left_unique",
    "right_non_empty",
    "right_unique",
    "overlap_values",
    "overlap_left_rows",
    "overlap_right_rows",
    "duplicate_overlap_values",
    "focus_rows",
    "focus_overlap_rows",
    "focus_overlap_values",
    "sample_values",
    "decision",
    "notes",
)

MANUAL_BRIDGE_COLUMNS = (
    "webex_message_ref",
    "reportpo_etr_event_number",
    "shared_job_id_or_ticket_id",
    "po_event_number",
    "review_status",
    "reviewed_by",
    "reviewed_at",
    "notes",
)

KEY_TOKENS = (
    "event",
    "job",
    "ticket",
    "work",
    "order",
    "request",
    "ref",
    "reference",
    "id",
    "no",
    "number",
)

CONTEXT_TOKENS = (
    "device",
    "feeder",
    "gis",
    "status",
    "notify",
    "time",
    "date",
    "cause",
    "type",
    "office",
    "area",
)

ETR_ENTITY = "ETR_OU"
PO_ENTITY = "PO"
PENDING_ENTITY = "Pending"

ETR_CANONICAL_MAP = {
    "eventid": "event_number",
    "event_id": "event_number",
    "eventnumber": "event_number",
    "event_number": "event_number",
    "eventstarttime": "event_start_time",
    "event_start_time": "event_start_time",
    "eventcreatetime": "event_create_time",
    "event_create_time": "event_create_time",
    "firstrestoretime": "first_restore_time",
    "first_restore_time": "first_restore_time",
    "eventetrtime": "event_etr_time",
    "event_etr_time": "event_etr_time",
    "eventendtime": "event_end_time",
    "event_end_time": "event_end_time",
    "etrfirsttime": "etr_first_time",
    "etr_first_time": "etr_first_time",
    "ipdatetime": "ip_datetime",
    "ip_datetime": "ip_datetime",
    "devicename": "device_id",
    "device_name": "device_id",
    "deviceid": "device_id",
    "device_id": "device_id",
    "feeder": "feeder",
    "officename": "office",
    "office": "office",
    "areaname": "area",
    "area": "area",
    "eventtype": "event_type",
    "event_type": "event_type",
    "eventstatus": "event_status",
    "event_status": "event_status",
    "etrtype": "etr_type",
    "etr_type": "etr_type",
    "etrtypedescription": "etr_type_description",
    "etr_type_description": "etr_type_description",
    "causegroup": "cause_group",
    "cause_group": "cause_group",
    "causecode": "cause_code",
    "cause_code": "cause_code",
    "worktype": "work_type",
    "work_type": "work_type",
    "jobstatus": "job_status_at_notification",
    "job_status": "job_status_at_notification",
}

PO_CANONICAL_MAP = {
    "eventid": "event_number",
    "event_id": "event_number",
    "eventnumber": "event_number",
    "event_number": "event_number",
    "opdeviceid": "op_device_id",
    "op_device_id": "op_device_id",
    "opdevicetype": "op_device_type",
    "op_device_type": "op_device_type",
    "opdevicegistag": "op_device_gis_tag",
    "op_device_gis_tag": "op_device_gis_tag",
    "feeder": "feeder",
    "officename": "office",
    "office": "office",
    "areaname": "area",
    "area": "area",
    "mainoffice": "main_office",
    "main_office": "main_office",
    "branch": "branch",
    "crdatetime": "cr_datetime",
    "cr_datetime": "cr_datetime",
    "apdatetime": "ap_datetime",
    "ap_datetime": "ap_datetime",
    "nodatetime": "no_datetime",
    "no_datetime": "no_datetime",
    "ipdatetime": "ip_datetime",
    "ip_datetime": "ip_datetime",
    "lastrestoredatetime": "last_restore_datetime",
    "last_restore_datetime": "last_restore_datetime",
    "cldatetime": "cl_datetime",
    "cl_datetime": "cl_datetime",
    "notifystatus": "notify_status",
    "notify_status": "notify_status",
    "notified": "notified",
    "notifyintime": "notify_in_time",
    "notify_in_time": "notify_in_time",
    "groupdevicetype": "group_device_type",
    "group_device_type": "group_device_type",
    "voltagelevel": "voltage_level",
    "voltage_level": "voltage_level",
    "stdresult": "std_result",
    "std_result": "std_result",
}

BASE_OVERLAP_PAIRS = (
    ("event_number", "event_number", "event_id_bridge", "strong_shared_key_candidate"),
    (
        "shared_job_id_or_ticket_id",
        "shared_job_id_or_ticket_id",
        "owner_requested_shared_job_ticket",
        "strong_shared_key_candidate",
    ),
    ("job_id", "job_id", "job_id_bridge", "strong_shared_key_candidate"),
    ("ticket_id", "ticket_id", "ticket_id_bridge", "strong_shared_key_candidate"),
    ("work_order_id", "work_order_id", "work_order_bridge", "strong_shared_key_candidate"),
    ("request_id", "request_id", "request_id_bridge", "strong_shared_key_candidate"),
    ("order_id", "order_id", "order_id_bridge", "strong_shared_key_candidate"),
    ("device_id", "op_device_id", "device_context", "audit_context_only"),
    ("device_id", "op_device_gis_tag", "device_gis_context", "audit_context_only"),
    ("feeder", "feeder", "feeder_context", "audit_context_only"),
    ("office", "office", "office_context", "audit_context_only"),
    ("office", "main_office", "office_context", "audit_context_only"),
    ("area", "area", "area_context", "audit_context_only"),
    ("event_status", "notify_status", "status_context", "audit_context_only"),
    ("ip_datetime", "ip_datetime", "timestamp_context", "audit_context_only"),
)


def build_reportpo_shared_key_discovery(
    model_inventory_csv: str | Path,
    visual_inventory_csv: str | Path,
    features_csv: str | Path,
    lifecycle_csv: str | Path,
    event_bridge_csv: str | Path,
    candidates_output: str | Path,
    overlap_output: str | Path,
    markdown_output: str | Path,
    manual_template_output: str | Path | None = None,
    pathfinding_report: str | Path | None = None,
) -> dict[str, Any]:
    feature_headers = _read_headers(features_csv)
    lifecycle_headers = _read_headers(lifecycle_csv)
    focus_rows = _read_csv(event_bridge_csv)
    visual_counts = _load_visual_counts(visual_inventory_csv)
    candidates = _discover_candidates(model_inventory_csv, feature_headers, lifecycle_headers, visual_counts)
    overlap_specs = _build_overlap_specs(feature_headers, lifecycle_headers)
    etr_columns = sorted({spec[0] for spec in overlap_specs if spec[0] in feature_headers})
    po_columns = sorted({spec[1] for spec in overlap_specs if spec[1] in lifecycle_headers})
    focus_event_numbers = {
        str(row.get("reportpo_etr_event_number") or "").strip()
        for row in focus_rows
        if str(row.get("reportpo_etr_event_number") or "").strip()
    }
    feature_profiles, focus_feature_rows = _profile_csv(
        features_csv,
        etr_columns,
        lookup_key="event_number",
        lookup_values=focus_event_numbers,
        lookup_columns=etr_columns,
    )
    lifecycle_profiles, _ = _profile_csv(lifecycle_csv, po_columns)
    candidates = _add_profile_to_candidates(candidates, feature_headers, lifecycle_headers, feature_profiles, lifecycle_profiles, focus_rows, focus_feature_rows)
    overlap_rows = _build_overlap_rows(
        overlap_specs,
        feature_headers,
        lifecycle_headers,
        feature_profiles,
        lifecycle_profiles,
        focus_rows,
        focus_feature_rows,
    )
    summary = _summarize(candidates, overlap_rows, focus_rows)
    shared_key_found = _shared_key_found(overlap_rows)
    summary["shared_key_found"] = shared_key_found
    _write_csv(candidates_output, CANDIDATE_COLUMNS, candidates)
    _write_csv(overlap_output, OVERLAP_COLUMNS, overlap_rows)
    manual_rows: list[dict[str, str]] = []
    if manual_template_output and not shared_key_found:
        manual_rows = _manual_bridge_rows(focus_rows)
        _write_csv(manual_template_output, MANUAL_BRIDGE_COLUMNS, manual_rows)
    output = Path(markdown_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_render_markdown(summary, overlap_rows, manual_template_output if manual_rows else None), encoding="utf-8-sig")
    if pathfinding_report:
        _update_pathfinding_report(pathfinding_report, summary, markdown_output, manual_template_output if manual_rows else None)
    return {
        **summary,
        "model_inventory_csv": str(model_inventory_csv),
        "visual_inventory_csv": str(visual_inventory_csv),
        "features_csv": str(features_csv),
        "lifecycle_csv": str(lifecycle_csv),
        "event_bridge_csv": str(event_bridge_csv),
        "candidates_output": str(candidates_output),
        "overlap_output": str(overlap_output),
        "markdown_output": str(markdown_output),
        "manual_template_output": str(manual_template_output) if manual_rows else None,
        "pathfinding_report": str(pathfinding_report) if pathfinding_report else None,
    }


def load_approved_manual_bridge_rows(path: str | Path) -> list[dict[str, str]]:
    if not Path(path).exists():
        return []
    rows = []
    for row in _read_csv(path):
        if str(row.get("review_status") or "").strip().lower() != "approved":
            continue
        if not (str(row.get("shared_job_id_or_ticket_id") or "").strip() or str(row.get("po_event_number") or "").strip()):
            continue
        rows.append(row)
    return rows


def _discover_candidates(
    model_inventory_csv: str | Path,
    feature_headers: set[str],
    lifecycle_headers: set[str],
    visual_counts: dict[tuple[str, str], dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in _read_csv(model_inventory_csv):
        entity = str(row.get("entity") or "").strip()
        prop = str(row.get("property") or "").strip()
        if not entity or not prop:
            continue
        if entity not in {ETR_ENTITY, PO_ENTITY, PENDING_ENTITY} and not _is_candidate_name(prop):
            continue
        side, canonical = _canonical_for_property(entity, prop, feature_headers, lifecycle_headers)
        if entity in {ETR_ENTITY, PO_ENTITY, PENDING_ENTITY} or canonical or _is_candidate_name(prop):
            rows.append(
                _candidate_row(
                    entity=entity,
                    prop=prop,
                    side=side,
                    canonical=canonical,
                    role=row.get("role", ""),
                    data_type_label=row.get("data_type_label", ""),
                    visual_count=row.get("visual_count", "") or visual_counts.get((entity, prop), {}).get("visual_count", ""),
                    visual_ids=row.get("visual_ids", "") or visual_counts.get((entity, prop), {}).get("visual_ids", ""),
                    source_evidence="model_inventory",
                )
            )
    for entity, side, headers in ((ETR_ENTITY, "etr", feature_headers), (PO_ENTITY, "po", lifecycle_headers)):
        for header in sorted(headers):
            if not _is_candidate_name(header):
                continue
            rows.append(
                _candidate_row(
                    entity=entity,
                    prop=header,
                    side=side,
                    canonical=header,
                    role="canonical_column",
                    data_type_label="",
                    visual_count="",
                    visual_ids="",
                    source_evidence="canonical_header",
                )
            )
    output: list[dict[str, str]] = []
    for row in rows:
        key = (
            row.get("entity", ""),
            row.get("property", ""),
            row.get("canonical_side", ""),
            row.get("canonical_column", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        row["candidate_id"] = str(len(output) + 1)
        output.append(row)
    return output


def _candidate_row(
    *,
    entity: str,
    prop: str,
    side: str,
    canonical: str,
    role: str,
    data_type_label: str,
    visual_count: str,
    visual_ids: str,
    source_evidence: str,
) -> dict[str, str]:
    category = _category(prop)
    key_hint = _key_hint(prop)
    return {
        "candidate_id": "",
        "entity": entity,
        "property": prop,
        "canonical_side": side,
        "canonical_column": canonical,
        "category": category,
        "key_hint": key_hint,
        "key_strength": _candidate_strength(prop, key_hint),
        "role": role,
        "data_type_label": data_type_label,
        "visual_count": str(visual_count or ""),
        "visual_ids": str(visual_ids or ""),
        "available_in_canonical": "",
        "non_empty_values": "",
        "unique_values": "",
        "duplicate_values": "",
        "focus_values": "",
        "source_evidence": source_evidence,
        "notes": _candidate_notes(entity, prop, canonical, key_hint),
    }


def _add_profile_to_candidates(
    rows: list[dict[str, str]],
    feature_headers: set[str],
    lifecycle_headers: set[str],
    feature_profiles: dict[str, Counter[str]],
    lifecycle_profiles: dict[str, Counter[str]],
    focus_rows: list[dict[str, str]],
    focus_feature_rows: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    for row in rows:
        side = row.get("canonical_side") or ""
        column = row.get("canonical_column") or ""
        available = (side == "etr" and column in feature_headers) or (side == "po" and column in lifecycle_headers)
        row["available_in_canonical"] = "yes" if available else "no"
        counter = feature_profiles.get(column, Counter()) if side == "etr" else lifecycle_profiles.get(column, Counter())
        if counter:
            row["non_empty_values"] = str(sum(counter.values()))
            row["unique_values"] = str(len(counter))
            row["duplicate_values"] = str(sum(1 for value_count in counter.values() if value_count > 1))
        if side == "etr" and column:
            row["focus_values"] = str(len(_focus_values(focus_rows, focus_feature_rows, column)))
    return rows


def _build_overlap_specs(feature_headers: set[str], lifecycle_headers: set[str]) -> list[tuple[str, str, str, str]]:
    specs = list(BASE_OVERLAP_PAIRS)
    for left in feature_headers:
        if not _is_strong_id_name(left):
            continue
        for right in lifecycle_headers:
            if _norm_name(left) == _norm_name(right) and _is_strong_id_name(right):
                specs.append((left, right, f"{left}_bridge", "strong_shared_key_candidate"))
    for left in feature_headers:
        if not _job_ticket_like(left):
            continue
        for right in lifecycle_headers:
            if _job_ticket_like(right) and _name_family(left) == _name_family(right):
                specs.append((left, right, f"{_name_family(left)}_bridge", "strong_shared_key_candidate"))
    output = []
    seen: set[tuple[str, str]] = set()
    for left, right, purpose, strength in specs:
        key = (left, right)
        if key in seen:
            continue
        seen.add(key)
        output.append((left, right, purpose, strength))
    return output


def _build_overlap_rows(
    specs: list[tuple[str, str, str, str]],
    feature_headers: set[str],
    lifecycle_headers: set[str],
    feature_profiles: dict[str, Counter[str]],
    lifecycle_profiles: dict[str, Counter[str]],
    focus_rows: list[dict[str, str]],
    focus_feature_rows: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    rows = []
    for left, right, purpose, strength in specs:
        left_counter = feature_profiles.get(left, Counter())
        right_counter = lifecycle_profiles.get(right, Counter())
        focus_values = _focus_values(focus_rows, focus_feature_rows, left)
        status, overlap_values, duplicate_values = _overlap_status(
            left in feature_headers,
            right in lifecycle_headers,
            left_counter,
            right_counter,
        )
        focus_overlap = {value for value in focus_values if value in right_counter}
        row = {
            "left_side": "etr",
            "left_entity": ETR_ENTITY,
            "left_field": left,
            "right_side": "po",
            "right_entity": PO_ENTITY,
            "right_field": right,
            "join_purpose": purpose,
            "key_strength": strength,
            "status": status,
            "left_non_empty": str(sum(left_counter.values())),
            "left_unique": str(len(left_counter)),
            "right_non_empty": str(sum(right_counter.values())),
            "right_unique": str(len(right_counter)),
            "overlap_values": str(len(overlap_values)),
            "overlap_left_rows": str(sum(left_counter[value] for value in overlap_values)),
            "overlap_right_rows": str(sum(right_counter[value] for value in overlap_values)),
            "duplicate_overlap_values": str(len(duplicate_values)),
            "focus_rows": str(len(focus_rows)),
            "focus_overlap_rows": str(sum(1 for value in focus_values if value in right_counter)),
            "focus_overlap_values": str(len(focus_overlap)),
            "sample_values": ";".join(sorted(overlap_values)[:5]),
            "decision": _overlap_decision(status, strength),
            "notes": _overlap_notes(status, strength, purpose),
        }
        rows.append(row)
    return sorted(rows, key=_overlap_sort_key)


def _overlap_status(
    left_exists: bool,
    right_exists: bool,
    left_counter: Counter[str],
    right_counter: Counter[str],
) -> tuple[str, set[str], set[str]]:
    if not left_exists or not right_exists:
        return "missing_field", set(), set()
    overlap_values = set(left_counter).intersection(right_counter)
    if not overlap_values:
        return "no_overlap", set(), set()
    duplicate_values = {
        value for value in overlap_values if left_counter.get(value, 0) > 1 or right_counter.get(value, 0) > 1
    }
    if duplicate_values:
        return "ambiguous_duplicate", overlap_values, duplicate_values
    return "exact_match", overlap_values, set()


def _focus_values(
    focus_rows: list[dict[str, str]],
    focus_feature_rows: dict[str, dict[str, str]],
    left_column: str,
) -> list[str]:
    output = []
    for row in focus_rows:
        value = ""
        if left_column == "event_number":
            value = row.get("reportpo_etr_event_number", "")
        elif left_column == "device_id":
            value = row.get("reportpo_etr_device_id", "") or row.get("device_id", "")
        elif left_column == "feeder":
            value = row.get("feeder", "")
        elif left_column == "event_start_time":
            value = row.get("reportpo_etr_event_start_time", "")
        else:
            event_number = str(row.get("reportpo_etr_event_number") or "").strip()
            value = focus_feature_rows.get(event_number, {}).get(left_column, "")
        value = str(value or "").strip()
        if value:
            output.append(value)
    return output


def _summarize(
    candidates: list[dict[str, str]],
    overlap_rows: list[dict[str, str]],
    focus_rows: list[dict[str, str]],
) -> dict[str, Any]:
    status_counts = Counter(row.get("status") or "<blank>" for row in overlap_rows)
    strong_rows = [row for row in overlap_rows if row.get("key_strength") == "strong_shared_key_candidate"]
    usable_strong_rows = [
        row
        for row in strong_rows
        if row.get("status") == "exact_match" and _to_int(row.get("focus_overlap_values")) > 0
    ]
    audit_context_rows = [row for row in overlap_rows if row.get("key_strength") == "audit_context_only"]
    return {
        "candidate_fields": len(candidates),
        "overlap_rows": len(overlap_rows),
        "high_error_focus_rows": len(focus_rows),
        "sek06_focus_rows": sum(1 for row in focus_rows if str(row.get("feeder") or "").strip().upper() == "SEK06"),
        "overlap_status_counts": dict(status_counts.most_common()),
        "strong_key_candidates": len(strong_rows),
        "usable_strong_key_candidates": len(usable_strong_rows),
        "audit_context_pairs_with_overlap": sum(
            1 for row in audit_context_rows if row.get("status") in {"exact_match", "ambiguous_duplicate"}
        ),
        "decision": "shared_key_found" if usable_strong_rows else "shared_key_not_found",
        "recommended_next": (
            "Validate the candidate shared key with the source owner, then build a lifecycle feature challenger."
            if usable_strong_rows
            else "Use the request pack or approved manual bridge template; do not tune or promote the model yet."
        ),
    }


def _shared_key_found(overlap_rows: list[dict[str, str]]) -> bool:
    return any(
        row.get("key_strength") == "strong_shared_key_candidate"
        and row.get("status") == "exact_match"
        and _to_int(row.get("focus_overlap_values")) > 0
        for row in overlap_rows
    )


def _manual_bridge_rows(focus_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    seen: set[tuple[str, str]] = set()
    for row in focus_rows:
        key = (row.get("webex_message_ref", ""), row.get("reportpo_etr_event_number", ""))
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "webex_message_ref": row.get("webex_message_ref", ""),
                "reportpo_etr_event_number": row.get("reportpo_etr_event_number", ""),
                "shared_job_id_or_ticket_id": "",
                "po_event_number": "",
                "review_status": "pending",
                "reviewed_by": "",
                "reviewed_at": "",
                "notes": "Generated by shared-key discovery; fill only after source-owner review.",
            }
        )
    return rows


def _render_markdown(
    summary: dict[str, Any],
    overlap_rows: list[dict[str, str]],
    manual_template_output: str | Path | None,
) -> str:
    lines = [
        "# ReportPO/eRespond Shared-Key Discovery",
        "",
        "Purpose: discover whether ReportPO ETR rows and PO lifecycle rows contain a shared key that can bridge high-error AIS ETR shadow events. This is audit-only and does not fill truth or train a model.",
        "",
        "## Summary",
        "",
        f"- Candidate fields reviewed: {summary['candidate_fields']}",
        f"- Overlap checks run: {summary['overlap_rows']}",
        f"- High-error focus rows: {summary['high_error_focus_rows']}",
        f"- SEK06 focus rows: {summary['sek06_focus_rows']}",
        f"- Decision: `{summary['decision']}`",
        f"- Recommended next: {summary['recommended_next']}",
        "",
        "## Overlap Status",
        "",
        "| Status | Checks |",
        "| --- | ---: |",
    ]
    for status, count in summary["overlap_status_counts"].items():
        lines.append(f"| {status} | {count} |")
    lines.extend(
        [
            "",
            "## Priority Key Checks",
            "",
            "| ETR field | PO field | Purpose | Strength | Status | Focus overlap | Decision |",
            "| --- | --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for row in overlap_rows[:20]:
        lines.append(
            "| {left} | {right} | {purpose} | {strength} | {status} | {focus} | {decision} |".format(
                left=row.get("left_field", ""),
                right=row.get("right_field", ""),
                purpose=row.get("join_purpose", ""),
                strength=row.get("key_strength", ""),
                status=row.get("status", ""),
                focus=row.get("focus_overlap_values", ""),
                decision=row.get("decision", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `strong_shared_key_candidate` means the field could bridge ETR and PO lifecycle at event/job/ticket grain if it overlaps on the high-error focus set.",
            "- `audit_context_only` means the overlap can explain context, but is too broad to fill lifecycle truth automatically.",
            "- `ambiguous_duplicate` means the value exists on both sides but appears multiple times, so it needs a second key or owner validation.",
        ]
    )
    if manual_template_output:
        lines.extend(
            [
                "",
                "## Manual Bridge Fallback",
                "",
                f"- Template created: `{manual_template_output}`",
                "- Rows are generated as `pending`; future audits should use only rows reviewed as `approved`.",
            ]
        )
    lines.extend(
        [
            "",
            "## Production Decision",
            "",
            "- Production customer send remains blocked.",
            "- Model tuning/promotion remains blocked until a lifecycle bridge passes this audit on the high-error rows.",
            "",
            "## Safety Notes",
            "",
            "- Outputs use redacted message references, device context, feeder context, and ReportPO event identifiers only.",
            "- Outputs exclude source chat bodies, space identifiers, credential values, meter-id lists, and unnecessary customer identity fields.",
        ]
    )
    return "\n".join(lines) + "\n"


def _update_pathfinding_report(
    path: str | Path,
    summary: dict[str, Any],
    markdown_output: str | Path,
    manual_template_output: str | Path | None,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = output.read_text(encoding="utf-8-sig") if output.exists() else "# AIS ETR Model Pathfinding Next Report\n"
    start = "<!-- reportpo-shared-key-discovery:start -->"
    end = "<!-- reportpo-shared-key-discovery:end -->"
    section_lines = [
        start,
        "",
        "## ReportPO/eRespond Shared-Key Discovery Decision",
        "",
        f"- Generated at: {datetime.now().isoformat(timespec='seconds')}",
        f"- Decision: `{summary['decision']}`",
        f"- High-error focus rows: {summary['high_error_focus_rows']}",
        f"- SEK06 focus rows: {summary['sek06_focus_rows']}",
        f"- Usable strong shared-key candidates: {summary['usable_strong_key_candidates']}",
        f"- Full discovery report: `{markdown_output}`",
        f"- Next action: {summary['recommended_next']}",
    ]
    if manual_template_output:
        section_lines.append(f"- Manual bridge fallback: `{manual_template_output}`")
    section_lines.extend(
        [
            "",
            "Production customer send remains blocked until the bridge is validated and the sustained-outage evaluation gate passes.",
            "",
            end,
        ]
    )
    section = "\n".join(section_lines) + "\n"
    if start in existing and end in existing:
        prefix = existing.split(start, 1)[0].rstrip()
        suffix = existing.split(end, 1)[1].lstrip()
        text = f"{prefix}\n\n{section}"
        if suffix:
            text += "\n" + suffix
    else:
        text = existing.rstrip() + "\n\n" + section
    output.write_text(text, encoding="utf-8-sig")


def _canonical_for_property(
    entity: str,
    prop: str,
    feature_headers: set[str],
    lifecycle_headers: set[str],
) -> tuple[str, str]:
    normalized = _norm_name(prop)
    if entity == ETR_ENTITY:
        mapped = ETR_CANONICAL_MAP.get(normalized)
        return "etr", mapped or _canonical_header_match(prop, feature_headers)
    if entity == PO_ENTITY:
        mapped = PO_CANONICAL_MAP.get(normalized)
        return "po", mapped or _canonical_header_match(prop, lifecycle_headers)
    if entity == PENDING_ENTITY:
        return "pending", ""
    return "", ""


def _canonical_header_match(prop: str, headers: set[str]) -> str:
    normalized = _norm_name(prop)
    for header in headers:
        if _norm_name(header) == normalized:
            return header
    return ""


def _profile_csv(
    path: str | Path,
    selected_columns: list[str],
    *,
    lookup_key: str | None = None,
    lookup_values: set[str] | None = None,
    lookup_columns: list[str] | None = None,
) -> tuple[dict[str, Counter[str]], dict[str, dict[str, str]]]:
    profiles = {column: Counter() for column in selected_columns}
    lookup: dict[str, dict[str, str]] = {}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        selected = [column for column in selected_columns if column in headers]
        for row in reader:
            for column in selected:
                value = str(row.get(column) or "").strip()
                if value:
                    profiles[column][value] += 1
            if lookup_key and lookup_values and lookup_key in headers:
                key = str(row.get(lookup_key) or "").strip()
                if key in lookup_values and key not in lookup:
                    lookup[key] = {
                        column: str(row.get(column) or "").strip()
                        for column in (lookup_columns or [])
                        if column in headers
                    }
    return profiles, lookup


def _load_visual_counts(path: str | Path) -> dict[tuple[str, str], dict[str, str]]:
    if not Path(path).exists():
        return {}
    counts: dict[tuple[str, str], Counter[str]] = {}
    for row in _read_csv(path):
        entity = str(row.get("entity") or "").strip()
        prop = str(row.get("property") or "").strip()
        visual_id = str(row.get("visual_id") or "").strip()
        if not entity or not prop:
            continue
        counts.setdefault((entity, prop), Counter())
        if visual_id:
            counts[(entity, prop)][visual_id] += 1
    output = {}
    for key, counter in counts.items():
        output[key] = {
            "visual_count": str(sum(counter.values())),
            "visual_ids": ";".join(sorted(counter)[:20]),
        }
    return output


def _read_headers(path: str | Path) -> set[str]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        return set(next(reader, []))


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


def _is_candidate_name(name: str) -> bool:
    normalized = _norm_name(name)
    return any(token in normalized for token in KEY_TOKENS + CONTEXT_TOKENS)


def _is_strong_id_name(name: str) -> bool:
    normalized = _norm_name(name)
    return any(token in normalized for token in ("event", "job", "ticket", "workorder", "request", "order", "ref")) or normalized.endswith("id")


def _job_ticket_like(name: str) -> bool:
    normalized = _norm_name(name)
    return any(token in normalized for token in ("job", "ticket", "workorder", "request", "order"))


def _name_family(name: str) -> str:
    normalized = _norm_name(name)
    for family in ("job", "ticket", "workorder", "request", "order", "event"):
        if family in normalized:
            return family
    return normalized


def _category(name: str) -> str:
    normalized = _norm_name(name)
    if any(token in normalized for token in ("time", "date", "datetime")):
        return "timestamp"
    if "status" in normalized or "notify" in normalized:
        return "status"
    if "device" in normalized or "feeder" in normalized or "gis" in normalized:
        return "network_context"
    if "cause" in normalized or "work" in normalized or "type" in normalized:
        return "operations_context"
    if any(token in normalized for token in KEY_TOKENS):
        return "identifier"
    return "context"


def _key_hint(name: str) -> str:
    normalized = _norm_name(name)
    if _is_strong_id_name(normalized):
        return "id_like"
    if "device" in normalized or "feeder" in normalized or "gis" in normalized:
        return "device_like"
    if any(token in normalized for token in ("time", "date", "datetime")):
        return "time_like"
    if "status" in normalized or "notify" in normalized:
        return "status_like"
    if any(token in normalized for token in ("work", "cause", "type")):
        return "process_like"
    return "context_like"


def _candidate_strength(name: str, key_hint: str) -> str:
    normalized = _norm_name(name)
    if key_hint == "id_like" and any(token in normalized for token in ("event", "job", "ticket", "workorder", "request", "order", "ref")):
        return "strong_shared_key_candidate"
    if key_hint == "id_like" and normalized.endswith("id"):
        return "possible_shared_key_candidate"
    return "context_or_feature"


def _candidate_notes(entity: str, prop: str, canonical: str, key_hint: str) -> str:
    if entity == PENDING_ENTITY:
        return "Visible in Pending metadata; no canonical Pending export is used by this discovery yet."
    if not canonical:
        return "Candidate exists in metadata but is not present in the current canonical export."
    if key_hint == "id_like":
        return "Profiled as a potential bridge key if it overlaps at focus-event grain."
    return "Profiled as context only unless source owner validates event-grain semantics."


def _overlap_decision(status: str, strength: str) -> str:
    if status == "missing_field":
        return "request_owner_field"
    if status == "no_overlap":
        return "not_usable_for_lifecycle_bridge" if strength == "strong_shared_key_candidate" else "no_context_overlap"
    if status == "ambiguous_duplicate":
        return "needs_disambiguation_before_use" if strength == "strong_shared_key_candidate" else "audit_context_only"
    if status == "exact_match":
        return "candidate_shared_key_for_owner_validation" if strength == "strong_shared_key_candidate" else "audit_context_only"
    return "review"


def _overlap_notes(status: str, strength: str, purpose: str) -> str:
    if strength == "audit_context_only":
        return "Context overlap only; do not use to fill truth or lifecycle fields automatically."
    if status == "exact_match":
        return "Strong key overlaps on focus values; validate with source owner before challenger modeling."
    if status == "ambiguous_duplicate":
        return "Shared-looking values are duplicated; require second key or manual approval."
    if status == "missing_field":
        return f"Requested field for {purpose} is missing from at least one canonical export."
    return "No overlap found for current exports."


def _overlap_sort_key(row: dict[str, str]) -> tuple[int, int, int, str, str]:
    status_rank = {"exact_match": 0, "ambiguous_duplicate": 1, "no_overlap": 2, "missing_field": 3}
    strength_rank = {"strong_shared_key_candidate": 0, "audit_context_only": 1}
    return (
        strength_rank.get(row.get("key_strength", ""), 9),
        status_rank.get(row.get("status", ""), 9),
        -_to_int(row.get("focus_overlap_values")),
        row.get("left_field", ""),
        row.get("right_field", ""),
    )


def _norm_name(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").strip()))
    except ValueError:
        return 0
