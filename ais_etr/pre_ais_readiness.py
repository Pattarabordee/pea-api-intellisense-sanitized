from __future__ import annotations

from collections import Counter
import csv
from pathlib import Path
import sqlite3
from typing import Any

from .ais_truth import AIS_TRUTH_INPUT_COLUMNS, import_ais_truth, match_ais_truth_to_shadow
from .db import RuntimeDb
from .schemas import OutageDevice, OutageEvent
from .truth_quality import (
    GATE_COVERAGE_MAX,
    GATE_COVERAGE_MIN,
    GATE_Q50_MAE_MAX,
    MIN_SUSTAINED_ROWS_FOR_TUNING,
)


DEFAULT_INTAKE_DIR = Path("runtime/ais_truth_intake")
DEFAULT_PRE_AIS_EVIDENCE_PACK = Path("runtime/pre_ais_truth_readiness_pack.md")

KIT_TEMPLATE_NAME = "ais_truth_template.csv"
KIT_SAMPLE_NAME = "ais_truth_sample_valid_invalid.csv"
KIT_README_NAME = "README_TH.md"


_SAMPLE_ROWS = [
    {
        "site_id": "AIS_SITE_VALID_001",
        "peano": "PEANO_PLACEHOLDER_001",
        "outage_start_time": "2026-06-17 10:00:00",
        "power_restore_time": "2026-06-17 10:45:00",
        "event_number": "",
        "device_id": "PFA05VB-01",
        "feeder": "PFA05",
        "source": "AIS_NOC",
        "notes": "valid sustained outage example; replace before real import",
    },
    {
        "site_id": "AIS_SITE_SHORT_001",
        "peano": "PEANO_PLACEHOLDER_002",
        "outage_start_time": "2026-06-17 11:00:00",
        "power_restore_time": "2026-06-17 11:03:00",
        "event_number": "",
        "device_id": "PFA06VB-01",
        "feeder": "PFA06",
        "source": "AIS_NOC",
        "notes": "short interruption review example; not used for sustained gate",
    },
    {
        "site_id": "AIS_SITE_MISSING_RESTORE_001",
        "peano": "PEANO_PLACEHOLDER_003",
        "outage_start_time": "2026-06-17 12:00:00",
        "power_restore_time": "",
        "event_number": "",
        "device_id": "PFA07VB-01",
        "feeder": "PFA07",
        "source": "AIS_NOC",
        "notes": "invalid example: restore time is required",
    },
    {
        "site_id": "AIS_SITE_NEGATIVE_001",
        "peano": "PEANO_PLACEHOLDER_004",
        "outage_start_time": "2026-06-17 13:00:00",
        "power_restore_time": "2026-06-17 12:55:00",
        "event_number": "",
        "device_id": "PFA08VB-01",
        "feeder": "PFA08",
        "source": "AIS_NOC",
        "notes": "invalid example: restore before outage",
    },
    {
        "site_id": "AIS_SITE_LONG_001",
        "peano": "PEANO_PLACEHOLDER_005",
        "outage_start_time": "2026-06-17 14:00:00",
        "power_restore_time": "2026-06-18 15:30:00",
        "event_number": "",
        "device_id": "PFA09VB-01",
        "feeder": "PFA09",
        "source": "AIS_NOC",
        "notes": "invalid example: duration over 24 hours needs review",
    },
]


def build_ais_truth_intake_kit(
    output_dir: str | Path = DEFAULT_INTAKE_DIR,
    *,
    force: bool = False,
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    template_path = root / KIT_TEMPLATE_NAME
    sample_path = root / KIT_SAMPLE_NAME
    readme_path = root / KIT_README_NAME

    template_status = _write_csv_if_allowed(
        template_path,
        list(AIS_TRUTH_INPUT_COLUMNS),
        [],
        force=force,
    )
    sample_status = _write_csv_if_allowed(
        sample_path,
        list(AIS_TRUTH_INPUT_COLUMNS),
        _SAMPLE_ROWS,
        force=force,
    )
    readme_status = _write_text_if_allowed(readme_path, _render_intake_readme(), force=force)

    return {
        "output_dir": str(root),
        "readme": str(readme_path),
        "template": str(template_path),
        "sample": str(sample_path),
        "template_status": template_status,
        "sample_status": sample_status,
        "readme_status": readme_status,
        "columns": list(AIS_TRUTH_INPUT_COLUMNS),
        "sample_rows": len(_SAMPLE_ROWS),
        "truth_definition": "power_restore_time - outage_start_time",
        "sustained_outage_policy": ">5 minutes",
    }


def run_ais_truth_dry_run(
    sample: str | Path,
    output_dir: str | Path = DEFAULT_INTAKE_DIR,
    *,
    run_match: bool = True,
) -> dict[str, Any]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    canonical = root / "dry_run_ais_truth_latest.csv"
    rejects = root / "dry_run_ais_truth_rejects.csv"
    import_result = import_ais_truth(sample, canonical, rejects)

    match_result: dict[str, Any] | None = None
    if run_match:
        private_dir = root / "private"
        private_dir.mkdir(parents=True, exist_ok=True)
        db_path = private_dir / "dry_run_runtime.sqlite"
        _build_dry_run_runtime_db(db_path)
        match_result = match_ais_truth_to_shadow(
            db_path,
            canonical,
            private_dir / "dry_run_shadow_truth_mapping_sample.csv",
            private_dir / "dry_run_ais_truth_shadow_match_audit.csv",
            overwrite=True,
        )

    return {
        "sample": str(sample),
        "canonical_output": str(canonical),
        "rejects_output": str(rejects),
        "import": import_result,
        "match": match_result,
        "accuracy_claim": "not_claimed_sample_data_only",
    }


def build_pre_ais_evidence_pack(
    output_markdown: str | Path = DEFAULT_PRE_AIS_EVIDENCE_PACK,
    *,
    intake_dir: str | Path = DEFAULT_INTAKE_DIR,
    db_path: str | Path = "runtime/ais_etr.sqlite",
    truth_quality_audit: str | Path = "runtime/truth_quality_audit.csv",
    shadow_model_comparison: str | Path = "runtime/shadow_model_comparison.csv",
    no_match_candidates: str | Path = "runtime/no_match_registry_repair_candidates_after_pfa05_repair.csv",
    station_mapping_review: str | Path = "runtime/station_mapping_review.csv",
) -> dict[str, Any]:
    output = Path(output_markdown)
    output.parent.mkdir(parents=True, exist_ok=True)
    intake_root = Path(intake_dir)

    runtime_counts = _runtime_counts(db_path)
    dry_run_summary = _ais_dry_run_summary(intake_root)
    truth_summary = _truth_quality_summary(truth_quality_audit)
    model_summary = _model_comparison_summary(shadow_model_comparison)
    topology_summary = _topology_summary(no_match_candidates)
    station_summary = _station_mapping_summary(station_mapping_review)

    output.write_text(
        _render_evidence_pack(
            intake_root=intake_root,
            runtime_counts=runtime_counts,
            dry_run_summary=dry_run_summary,
            truth_summary=truth_summary,
            model_summary=model_summary,
            topology_summary=topology_summary,
            station_summary=station_summary,
        ),
        encoding="utf-8-sig",
    )

    return {
        "output_markdown": str(output),
        "intake_dir": str(intake_root),
        "runtime_counts": runtime_counts,
        "dry_run_summary": dry_run_summary,
        "truth_summary": truth_summary,
        "topology_summary": topology_summary,
        "station_summary": station_summary,
        "recommendation": "wait_for_ais_truth_then_import_match_evaluate",
    }


def _build_dry_run_runtime_db(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    db = RuntimeDb(db_path)
    db.init()
    event_time = "2026-06-17T10:00:00"
    db.insert_webex_message(
        {
            "id": "dry-run-webex-message-001",
            "roomId": "dry-run-room",
            "created": event_time,
            "text": "Dry-run outage PFA05VB-01 at 2026-06-17 10:00",
        }
    )
    db.upsert_event(
        OutageEvent(
            event_id="dry-run-event-001",
            source="webex",
            webex_message_id="dry-run-webex-message-001",
            room_id="dry-run-room",
            raw_text="Dry-run outage PFA05VB-01 at 2026-06-17 10:00",
            created=event_time,
            event_time=event_time,
            district="พังโคน",
            site="พังโคน",
            outage_device=OutageDevice(device_type="CB", device_id="PFA05VB-01", feeder="PFA05"),
            parsed_fields={"event_number": None},
        )
    )


def _render_intake_readme() -> str:
    return f"""# AIS Truth Intake Kit

ไฟล์ชุดนี้ใช้ขอข้อมูล outage/restore truth จาก AIS เพื่อประเมิน AIS ETR shadow pilot เมื่อ AIS ส่งไฟล์กลับมา ระบบจะ import, validate, match กับ Webex shadow events, แล้วคำนวณ accuracy ได้ทันที

## ไฟล์ในชุดนี้

- `{KIT_TEMPLATE_NAME}`: template เปล่าสำหรับ AIS กรอกข้อมูลจริง
- `{KIT_SAMPLE_NAME}`: sample สำหรับทดสอบ validation เท่านั้น ห้ามใช้ claim accuracy จริง
- `dry_run_ais_truth_latest.csv`: canonical output จาก dry-run หลังรันคำสั่งทดสอบ
- `dry_run_ais_truth_rejects.csv`: rejected rows จาก dry-run หลังรันคำสั่งทดสอบ

## Columns ที่ต้องการ

| Column | Required | ความหมาย |
| --- | --- | --- |
| site_id | อย่างน้อย site_id หรือ peano | รหัส site ของ AIS ถ้ามี |
| peano | อย่างน้อย site_id หรือ peano | PEA meter number ที่ผูกกับ AIS site ถ้ามี |
| outage_start_time | required | เวลาที่ AIS เห็นว่าไฟดับจริงที่ site/meter |
| power_restore_time | required | เวลาที่ AIS เห็นว่าไฟกลับจริงที่ site/meter |
| event_number | optional | เลขเหตุการณ์ OMS/DMS/erespond ถ้ามี |
| device_id | optional | อุปกรณ์ป้องกันที่เกี่ยวข้อง เช่น CB/Recloser/Switch |
| feeder | optional | feeder เช่น PFA05 |
| source | optional | แหล่งข้อมูล เช่น AIS_NOC |
| notes | optional | หมายเหตุที่ช่วยตรวจคุณภาพข้อมูล |

## นิยาม ETR truth ที่จะใช้

`actual_restoration_minutes = power_restore_time - outage_start_time`

โปรดอย่าใช้เวลาเปิด/ปิด ticket, เวลาออกจากสำนักงาน, เวลากลับถึงสำนักงาน, หรือค่า ETR ที่เคยแจ้งเป็น actual restoration truth เพราะไม่ใช่เวลาที่ลูกค้าเห็นว่าไฟกลับจริง

## Sustained outage policy

- `<=1 นาที`: momentary/micro review
- `>1 ถึง <=5 นาที`: short interruption review
- `>5 นาที`: sustained outage eligible สำหรับ customer-facing ETR evaluation gate

Model gate จะใช้เฉพาะ outage ที่ `>5 นาที` และต้องมี sustained truth อย่างน้อย {MIN_SUSTAINED_ROWS_FOR_TUNING} events ก่อนเริ่ม tune/promote model

## รูปแบบเวลา

ใช้เวลาท้องถิ่น Asia/Bangkok เช่น `2026-06-17 10:45:00` หรือ `17/06/2569 10:45`

## คำสั่งเมื่อได้รับไฟล์ AIS จริง

```powershell
python -m ais_etr ais-truth-import --source <AIS_FILE.csv_or_xlsx> --output runtime/ais_truth_latest.csv --rejects-output runtime/ais_truth_rejects.csv
python -m ais_etr ais-truth-match-shadow --ais-truth runtime/ais_truth_latest.csv --output runtime/shadow_truth_mapping_ais.csv --audit runtime/ais_truth_shadow_match_audit.csv --overwrite
python -m ais_etr shadow-model-compare --truth-mapping runtime/shadow_truth_mapping_ais.csv
python -m ais_etr shadow-truth-quality-audit
python -m ais_etr pre-ais-evidence-pack
```

## Data minimization

ส่งเฉพาะ field ที่จำเป็นต่อการ match และ evaluation ไม่ต้องส่งชื่อผู้จดทะเบียน, ที่อยู่เต็ม, เบอร์ติดต่อ, หรือข้อมูลลูกค้าอื่นที่ไม่เกี่ยวกับ outage/restore truth
"""


def _render_evidence_pack(
    *,
    intake_root: Path,
    runtime_counts: dict[str, int | None],
    dry_run_summary: dict[str, Any],
    truth_summary: dict[str, Any],
    model_summary: dict[str, Any],
    topology_summary: dict[str, Any],
    station_summary: dict[str, Any],
) -> str:
    sustained_rows = int(truth_summary.get("sustained_rows") or 0)
    gate_ready = sustained_rows >= MIN_SUSTAINED_ROWS_FOR_TUNING
    action = (
        "เริ่ม shadow challenger tuning ได้เมื่อ AIS truth ผ่าน validation"
        if gate_ready
        else "ยังไม่ควร tune/promote model จนกว่าจะมี sustained AIS truth เพิ่ม"
    )
    lines = [
        "# Pre-AIS Truth Readiness Pack",
        "",
        "เอกสารนี้สรุปงานที่ทำได้ก่อน AIS ส่ง outage/restore truth จริง โดยยังคง notification เป็น shadow mode เท่านั้น",
        "",
        "## Current Runtime Snapshot",
        "",
        "| Item | Count |",
        "| --- | ---: |",
    ]
    for key in ("webex_messages", "outage_events", "predictions", "notifications", "customer_assets"):
        lines.append(f"| {key} | {_blank(runtime_counts.get(key))} |")
    lines.extend(
        [
            "",
            "## AIS Truth Intake Kit",
            "",
            f"- Template: `{(intake_root / KIT_TEMPLATE_NAME).as_posix()}`",
            f"- Thai README: `{(intake_root / KIT_README_NAME).as_posix()}`",
            f"- Dry-run sample: `{(intake_root / KIT_SAMPLE_NAME).as_posix()}`",
            "- Truth target: `power_restore_time - outage_start_time`",
            "- Sustained outage policy: use only `>5 minutes` for customer-facing ETR gate",
            "",
            "## Dry-Run Validation",
            "",
            f"- Sample rows imported: {_blank(dry_run_summary.get('rows'))}",
            f"- Valid sustained rows: {_blank(dry_run_summary.get('ok_rows'))}",
            f"- Short/micro review rows: {_blank(dry_run_summary.get('review_short_rows'))}",
            f"- Rejected invalid rows: {_blank(dry_run_summary.get('reject_rows'))}",
            f"- Synthetic shadow match filled rows: {_blank(dry_run_summary.get('matched_mapping_rows'))}",
            "- Accuracy claim: not claimed; sample is for pipeline validation only.",
            "",
            "## Sustained-Only Evaluation Status",
            "",
            "| Metric | Value | Gate | Status |",
            "| --- | ---: | ---: | --- |",
            f"| Rows with truth | {_blank(truth_summary.get('with_truth'))} | - | observed |",
            f"| Sustained truth rows | {sustained_rows} | >= {MIN_SUSTAINED_ROWS_FOR_TUNING} | {'ready' if gate_ready else 'insufficient'} |",
            f"| Sustained q50 MAE | {_blank(truth_summary.get('sustained_current_mae'))} | <= {GATE_Q50_MAE_MAX:g} | {_mae_status(truth_summary.get('sustained_current_mae'))} |",
            f"| Sustained q10-q90 coverage | {_blank(truth_summary.get('sustained_current_coverage'))} | {GATE_COVERAGE_MIN:g}-{GATE_COVERAGE_MAX:g} | {_coverage_status(truth_summary.get('sustained_current_coverage'))} |",
            "",
            f"Decision: {action}",
            "",
            "## Shadow Model Comparison",
            "",
            f"- Comparison rows: {_blank(model_summary.get('rows'))}",
            f"- Rows with truth: {_blank(model_summary.get('with_truth'))}",
            f"- Current model MAE on all matched truth: {_blank(model_summary.get('current_mae_all_truth'))}",
            f"- Challenger model MAE on all matched truth: {_blank(model_summary.get('challenger_mae_all_truth'))}",
            "- Interpretation: use sustained-only metrics above for customer-facing gate; all-truth metrics still include momentary/short rows.",
            "",
            "## Matching And Topology Readiness",
            "",
            f"- Remaining no-match candidate groups after PFA05 repair: {_blank(topology_summary.get('candidate_groups'))}",
            f"- Events represented by those groups: {_blank(topology_summary.get('event_count_total'))}",
            f"- Highest-impact devices to review next: {_format_top_devices(topology_summary.get('top_devices') or [])}",
            f"- Station mapping unknown/pending rows: {_blank(station_summary.get('unknown_or_pending_rows'))}",
            "- Repair rule: apply only source-trace-confirmed private overrides; do not edit `upstream_result.xlsx` directly.",
            "",
            "## What To Do When AIS File Arrives",
            "",
            "1. Run `ais-truth-import` against the AIS CSV/XLSX and inspect rejects.",
            "2. Run `ais-truth-match-shadow` to produce `runtime/shadow_truth_mapping_ais.csv`.",
            "3. Run `shadow-model-compare` and `shadow-truth-quality-audit` on AIS truth.",
            "4. Promote no model until sustained truth is at least 30 rows and gate passes.",
            "",
            "## Safety Notes",
            "",
            "- This pack intentionally avoids raw chat text, source space identifiers, credential values, PEANO lists, customer registration names, and full customer addresses.",
            "- AIS sample rows are placeholders for validation only and must not be used for accuracy claims.",
            "- ReportPO truth remains provisional; AIS site outage/restore timestamps should become the primary evaluation truth once available.",
        ]
    )
    return "\n".join(lines) + "\n"


def _runtime_counts(db_path: str | Path) -> dict[str, int | None]:
    path = Path(db_path)
    tables = ["webex_messages", "outage_events", "predictions", "notifications", "customer_assets"]
    if not path.exists():
        return {table: None for table in tables}
    conn = sqlite3.connect(path)
    try:
        summary: dict[str, int | None] = {}
        for table in tables:
            try:
                summary[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.OperationalError:
                summary[table] = None
        return summary
    finally:
        conn.close()


def _truth_quality_summary(path: str | Path) -> dict[str, Any]:
    rows = _read_csv_if_exists(path)
    with_truth = len(rows)
    sustained_rows = [
        row for row in rows if row.get("evaluation_policy") == "sustained_outage_eligible"
    ]
    review_rows = [
        row
        for row in rows
        if row.get("evaluation_policy") in {"momentary_micro_review", "short_interruption_review"}
    ]
    return {
        "with_truth": with_truth,
        "sustained_rows": len(sustained_rows),
        "review_rows": len(review_rows),
        "sustained_current_mae": _mean_float(sustained_rows, "current_absolute_error"),
        "sustained_current_coverage": _coverage(sustained_rows, "current_covered_q10_q90"),
        "policy_counts": dict(Counter(row.get("evaluation_policy") or "" for row in rows)),
    }


def _ais_dry_run_summary(intake_root: Path) -> dict[str, Any]:
    canonical_rows = _read_csv_if_exists(intake_root / "dry_run_ais_truth_latest.csv")
    reject_rows = _read_csv_if_exists(intake_root / "dry_run_ais_truth_rejects.csv")
    mapping_rows = _read_csv_if_exists(
        intake_root / "private" / "dry_run_shadow_truth_mapping_sample.csv"
    )
    quality_counts = Counter(row.get("truth_quality") or "" for row in canonical_rows)
    return {
        "rows": len(canonical_rows),
        "ok_rows": quality_counts.get("OK", 0),
        "review_short_rows": quality_counts.get("REVIEW_SHORT", 0),
        "reject_rows": len(reject_rows),
        "matched_mapping_rows": sum(
            1 for row in mapping_rows if str(row.get("actual_restoration_minutes") or "").strip()
        ),
    }


def _model_comparison_summary(path: str | Path) -> dict[str, Any]:
    rows = _read_csv_if_exists(path)
    with_truth = [
        row
        for row in rows
        if _to_float(row.get("actual_restoration_minutes")) is not None
    ]
    return {
        "rows": len(rows),
        "with_truth": len(with_truth),
        "current_mae_all_truth": _mean_float(with_truth, "current_absolute_error"),
        "challenger_mae_all_truth": _mean_float(with_truth, "challenger_absolute_error"),
    }


def _topology_summary(path: str | Path) -> dict[str, Any]:
    rows = _read_csv_if_exists(path)
    top_devices = []
    event_count_total = 0
    for row in rows:
        event_count = int(_to_float(row.get("event_count")) or 0)
        event_count_total += event_count
        device = row.get("device_id") or row.get("candidate_device_id") or row.get("webex_device_id") or ""
        if device:
            top_devices.append({"device_id": device, "event_count": event_count})
    top_devices = sorted(top_devices, key=lambda item: item["event_count"], reverse=True)[:5]
    return {
        "candidate_groups": len(rows),
        "event_count_total": event_count_total,
        "top_devices": top_devices,
    }


def _station_mapping_summary(path: str | Path) -> dict[str, Any]:
    rows = _read_csv_if_exists(path)
    unknown_or_pending = [
        row
        for row in rows
        if (row.get("status") or "").strip().lower() in {"", "pending", "unknown"}
        or (row.get("scope") or "").strip().lower() in {"", "unknown", "pending"}
    ]
    return {
        "rows": len(rows),
        "unknown_or_pending_rows": len(unknown_or_pending),
    }


def _write_csv_if_allowed(
    path: Path,
    columns: list[str],
    rows: list[dict[str, str]],
    *,
    force: bool,
) -> str:
    if path.exists() and not force:
        return "exists"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows({column: row.get(column, "") for column in columns} for row in rows)
    return "created"


def _write_text_if_allowed(path: Path, content: str, *, force: bool) -> str:
    if path.exists() and not force:
        return "exists"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8-sig")
    return "created"


def _read_csv_if_exists(path: str | Path) -> list[dict[str, str]]:
    source = Path(path)
    if not source.exists():
        return []
    with source.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _mean_float(rows: list[dict[str, str]], column: str) -> float | None:
    values = [_to_float(row.get(column)) for row in rows]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _coverage(rows: list[dict[str, str]], column: str) -> float | None:
    values = [str(row.get(column) or "").strip().upper() for row in rows]
    values = [value for value in values if value in {"TRUE", "FALSE"}]
    if not values:
        return None
    return round(sum(1 for value in values if value == "TRUE") / len(values), 3)


def _to_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _blank(value: Any) -> str:
    return "" if value is None else str(value)


def _mae_status(value: Any) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "missing"
    return "pass" if numeric <= GATE_Q50_MAE_MAX else "fail"


def _coverage_status(value: Any) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "missing"
    return "pass" if GATE_COVERAGE_MIN <= numeric <= GATE_COVERAGE_MAX else "fail"


def _format_top_devices(devices: list[dict[str, Any]]) -> str:
    if not devices:
        return "none"
    return ", ".join(
        f"{item['device_id']} ({item['event_count']} events)" for item in devices[:5]
    )
