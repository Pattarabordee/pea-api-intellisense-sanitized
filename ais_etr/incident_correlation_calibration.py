from __future__ import annotations

import argparse
import csv
import hashlib
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable

SCORE_SCHEMA_VERSION = "incident-correlation-score-export.v1"
LABEL_SCHEMA_VERSION = "incident-correlation-review-label.v1"
REPORT_SCHEMA_VERSION = "incident-correlation-calibration-report.v1"
VALID_LABELS = {"SAME_INCIDENT", "DIFFERENT_INCIDENT", "INSUFFICIENT_EVIDENCE"}
VALID_RISK_TIERS = {"NORMAL", "HIGH", "CRITICAL"}
VALID_SPLITS = {"UNSPECIFIED", "CALIBRATION", "EVALUATION"}
SAFE_REF = re.compile(r"^[A-Za-z0-9_.:@-]{6,160}$")
HEX_HASH = re.compile(r"^[a-f0-9]{32,128}$")

_SCORE_FIELDS = {
    "schema_version",
    "pair_ref",
    "engine_version",
    "decision_hash",
    "confidence_score",
    "hard_veto",
    "eligible_for_unplanned",
    "flags",
}
_LABEL_FIELDS = {
    "schema_version",
    "pair_ref",
    "review_case_ref",
    "label",
    "risk_tier",
    "split",
}


@dataclass(frozen=True)
class ScoredRelationship:
    pair_ref: str
    engine_version: str
    decision_hash: str
    confidence_score: float
    hard_veto: bool
    eligible_for_unplanned: bool
    flags: tuple[str, ...]


@dataclass(frozen=True)
class ReviewLabel:
    pair_ref: str
    review_case_ref: str
    label: str
    risk_tier: str
    split: str


@dataclass(frozen=True)
class ReviewRecord:
    pair_ref: str
    review_case_ref: str
    engine_version: str
    decision_hash: str
    confidence_score: float
    hard_veto: bool
    eligible_for_unplanned: bool
    label: str
    risk_tier: str
    split: str
    flags: tuple[str, ...]


@dataclass(frozen=True)
class ThresholdMetrics:
    threshold: float
    rows: int
    same_incident: int
    different_incident: int
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float | None
    precision_wilson_low95: float | None
    recall: float | None
    recall_wilson_low95: float | None
    f1: float | None
    specificity: float | None
    false_merge_count: int
    false_split_count: int
    false_merge_high_critical: int
    hard_safety_pass: bool
    zero_false_merge_pass: bool


def load_scored_jsonl(path: str | Path) -> list[ScoredRelationship]:
    payloads = _load_jsonl(path)
    rows: list[ScoredRelationship] = []
    seen: dict[str, ScoredRelationship] = {}
    for line_number, payload in payloads:
        row = _validate_score(payload, line_number)
        previous = seen.get(row.pair_ref)
        if previous is not None:
            if previous != row:
                raise ValueError(f"line {line_number}: conflicting duplicate score pair_ref {row.pair_ref}")
            continue
        seen[row.pair_ref] = row
        rows.append(row)
    versions = sorted({row.engine_version for row in rows})
    if len(versions) > 1:
        raise ValueError(
            "mixed engine_version score export is not allowed; evaluate each engine version separately: "
            + ", ".join(versions)
        )
    return rows


def load_labels_jsonl(path: str | Path) -> list[ReviewLabel]:
    payloads = _load_jsonl(path)
    rows: list[ReviewLabel] = []
    seen: dict[str, ReviewLabel] = {}
    for line_number, payload in payloads:
        row = _validate_label(payload, line_number)
        previous = seen.get(row.pair_ref)
        if previous is not None:
            if previous != row:
                raise ValueError(f"line {line_number}: conflicting duplicate label pair_ref {row.pair_ref}")
            continue
        seen[row.pair_ref] = row
        rows.append(row)
    return rows


def join_review_records(
    scored: Iterable[ScoredRelationship], labels: Iterable[ReviewLabel]
) -> list[ReviewRecord]:
    score_by_ref = {row.pair_ref: row for row in scored}
    label_rows = list(labels)
    unknown = sorted({row.pair_ref for row in label_rows if row.pair_ref not in score_by_ref})
    if unknown:
        raise ValueError(f"review labels reference unknown score pairs: {unknown[:10]}")
    records: list[ReviewRecord] = []
    for label in label_rows:
        score = score_by_ref[label.pair_ref]
        records.append(
            ReviewRecord(
                pair_ref=score.pair_ref,
                review_case_ref=label.review_case_ref,
                engine_version=score.engine_version,
                decision_hash=score.decision_hash,
                confidence_score=score.confidence_score,
                hard_veto=score.hard_veto,
                eligible_for_unplanned=score.eligible_for_unplanned,
                label=label.label,
                risk_tier=label.risk_tier,
                split=label.split,
                flags=score.flags,
            )
        )
    return records


def evaluate_records(
    records: Iterable[ReviewRecord],
    *,
    step: float = 1.0,
) -> dict[str, Any]:
    items = list(records)
    if step <= 0 or step > 100:
        raise ValueError("step must be > 0 and <= 100")
    _validate_case_split_integrity(items)
    decisive = [record for record in items if record.label != "INSUFFICIENT_EVIDENCE"]
    insufficient = [record for record in items if record.label == "INSUFFICIENT_EVIDENCE"]
    subsets: dict[str, list[ReviewRecord]] = {"ALL": decisive}
    for split in ("CALIBRATION", "EVALUATION"):
        selected = [record for record in decisive if record.split == split]
        if selected:
            subsets[split] = selected

    thresholds = _threshold_grid(step)
    sweeps = {
        name: [evaluate_threshold(rows, threshold) for threshold in thresholds]
        for name, rows in subsets.items()
    }
    preferred_name = "EVALUATION" if "EVALUATION" in sweeps else "CALIBRATION" if "CALIBRATION" in sweeps else "ALL"
    preferred = sweeps[preferred_name]
    pareto = pareto_frontier(preferred)
    engine_versions = sorted({record.engine_version for record in items})

    status = "READY_FOR_REVIEWED_THRESHOLD_ANALYSIS"
    if not items:
        status = "NO_REVIEWED_DATA"
    elif not decisive:
        status = "NO_DECISIVE_LABELS"
    elif "EVALUATION" not in sweeps:
        status = "CALIBRATION_ONLY_NO_HELD_OUT_EVALUATION"

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": status,
        "engine_version": engine_versions[0] if len(engine_versions) == 1 else "",
        "review_rows": len(items),
        "decisive_rows": len(decisive),
        "insufficient_evidence_rows": len(insufficient),
        "same_incident_rows": sum(record.label == "SAME_INCIDENT" for record in decisive),
        "different_incident_rows": sum(record.label == "DIFFERENT_INCIDENT" for record in decisive),
        "split_counts": {
            split: sum(record.split == split for record in items)
            for split in sorted(VALID_SPLITS)
        },
        "preferred_analysis_split": preferred_name,
        "threshold_step": step,
        "sweeps": {name: [asdict(row) for row in values] for name, values in sweeps.items()},
        "pareto_frontier": [asdict(row) for row in pareto],
        "zero_false_merge_candidates": [
            asdict(row) for row in preferred if row.zero_false_merge_pass and row.tp > 0
        ],
        "hard_safety_candidates": [
            asdict(row) for row in preferred if row.hard_safety_pass and row.tp > 0
        ],
        "automatic_threshold_promotion": False,
        "promotion_reason": (
            "Threshold promotion is intentionally manual. Review the held-out evaluation split, "
            "false-merge safety floors, uncertainty bounds, and operational impact before changing runtime config."
        ),
    }


def _validate_case_split_integrity(records: Iterable[ReviewRecord]) -> None:
    splits_by_case: dict[str, set[str]] = {}
    for record in records:
        if record.split == "UNSPECIFIED":
            continue
        splits_by_case.setdefault(record.review_case_ref, set()).add(record.split)
    leaked = sorted(case for case, splits in splits_by_case.items() if len(splits) > 1)
    if leaked:
        raise ValueError(
            "review_case_ref leakage across CALIBRATION/EVALUATION splits is not allowed: "
            + ", ".join(leaked[:10])
        )


def evaluate_threshold(records: Iterable[ReviewRecord], threshold: float) -> ThresholdMetrics:
    rows = list(records)
    tp = fp = tn = fn = 0
    false_merge_high_critical = 0
    for record in rows:
        if record.label == "INSUFFICIENT_EVIDENCE":
            continue
        predicted_same = (
            record.eligible_for_unplanned
            and not record.hard_veto
            and record.confidence_score >= threshold
        )
        actual_same = record.label == "SAME_INCIDENT"
        if predicted_same and actual_same:
            tp += 1
        elif predicted_same and not actual_same:
            fp += 1
            if record.risk_tier in {"HIGH", "CRITICAL"}:
                false_merge_high_critical += 1
        elif not predicted_same and actual_same:
            fn += 1
        else:
            tn += 1
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    specificity = _ratio(tn, tn + fp)
    f1 = None
    if precision is not None and recall is not None and precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    return ThresholdMetrics(
        threshold=round(float(threshold), 6),
        rows=tp + fp + tn + fn,
        same_incident=tp + fn,
        different_incident=tn + fp,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=_round_or_none(precision),
        precision_wilson_low95=_round_or_none(_wilson_lower(tp, tp + fp)),
        recall=_round_or_none(recall),
        recall_wilson_low95=_round_or_none(_wilson_lower(tp, tp + fn)),
        f1=_round_or_none(f1),
        specificity=_round_or_none(specificity),
        false_merge_count=fp,
        false_split_count=fn,
        false_merge_high_critical=false_merge_high_critical,
        hard_safety_pass=false_merge_high_critical == 0,
        zero_false_merge_pass=fp == 0,
    )


def pareto_frontier(rows: Iterable[ThresholdMetrics]) -> list[ThresholdMetrics]:
    candidates = [row for row in rows if row.precision is not None and row.recall is not None]
    frontier: list[ThresholdMetrics] = []
    for candidate in candidates:
        dominated = False
        for other in candidates:
            if other is candidate:
                continue
            if (
                other.precision >= candidate.precision
                and other.recall >= candidate.recall
                and (
                    other.precision > candidate.precision
                    or other.recall > candidate.recall
                )
            ):
                dominated = True
                break
        if not dominated:
            frontier.append(candidate)
    return sorted(frontier, key=lambda row: (row.threshold, -(row.precision or 0), -(row.recall or 0)))


def write_outputs(result: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "incident_correlation_calibration_summary.json"
    report_path = root / "incident_correlation_calibration_report.md"
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sweep_paths: dict[str, str] = {}
    for split, rows in result.get("sweeps", {}).items():
        path = root / f"incident_correlation_threshold_sweep_{split.lower()}.csv"
        _write_csv(path, rows)
        sweep_paths[split] = str(path)
    pareto_path = root / "incident_correlation_pareto_frontier.csv"
    _write_csv(pareto_path, result.get("pareto_frontier", []))
    report_path.write_text(_render_markdown(result), encoding="utf-8")
    return {
        "summary": str(summary_path),
        "report": str(report_path),
        "pareto": str(pareto_path),
        **{f"sweep_{key.lower()}": value for key, value in sweep_paths.items()},
    }


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_jsonl(path: str | Path) -> list[tuple[int, Any]]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(source)
    rows: list[tuple[int, Any]] = []
    for line_number, raw_line in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append((line_number, json.loads(line)))
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
    return rows


def _validate_score(payload: Any, line_number: int) -> ScoredRelationship:
    _validate_field_set(payload, _SCORE_FIELDS, {"flags"}, line_number, "score")
    if payload.get("schema_version") != SCORE_SCHEMA_VERSION:
        raise ValueError(f"line {line_number}: schema_version must be {SCORE_SCHEMA_VERSION}")
    pair_ref = _safe_ref(payload.get("pair_ref"), "pair_ref", line_number)
    engine_version = _safe_ref(payload.get("engine_version"), "engine_version", line_number)
    decision_hash = str(payload.get("decision_hash") or "").strip().lower()
    if not HEX_HASH.fullmatch(decision_hash):
        raise ValueError(f"line {line_number}: decision_hash must be 32-128 lowercase hex characters")
    try:
        confidence_score = float(payload.get("confidence_score"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"line {line_number}: confidence_score must be numeric") from exc
    if not math.isfinite(confidence_score) or not (0 <= confidence_score <= 100):
        raise ValueError(f"line {line_number}: confidence_score must be between 0 and 100")
    hard_veto = payload.get("hard_veto")
    eligible = payload.get("eligible_for_unplanned")
    if type(hard_veto) is not bool or type(eligible) is not bool:
        raise ValueError(f"line {line_number}: hard_veto and eligible_for_unplanned must be booleans")
    raw_flags = payload.get("flags", [])
    if not isinstance(raw_flags, list) or any(not isinstance(flag, str) for flag in raw_flags):
        raise ValueError(f"line {line_number}: flags must be a list of strings")
    flags = tuple(sorted({_safe_ref(flag, "flag", line_number) for flag in raw_flags if flag.strip()}))
    return ScoredRelationship(
        pair_ref=pair_ref,
        engine_version=engine_version,
        decision_hash=decision_hash,
        confidence_score=confidence_score,
        hard_veto=hard_veto,
        eligible_for_unplanned=eligible,
        flags=flags,
    )


def _validate_label(payload: Any, line_number: int) -> ReviewLabel:
    _validate_field_set(payload, _LABEL_FIELDS, set(), line_number, "label")
    if payload.get("schema_version") != LABEL_SCHEMA_VERSION:
        raise ValueError(f"line {line_number}: schema_version must be {LABEL_SCHEMA_VERSION}")
    pair_ref = _safe_ref(payload.get("pair_ref"), "pair_ref", line_number)
    review_case_ref = _safe_ref(payload.get("review_case_ref"), "review_case_ref", line_number)
    label = str(payload.get("label") or "").strip().upper()
    if label not in VALID_LABELS:
        raise ValueError(f"line {line_number}: unsupported label {label!r}")
    risk_tier = str(payload.get("risk_tier") or "").strip().upper()
    if risk_tier not in VALID_RISK_TIERS:
        raise ValueError(f"line {line_number}: unsupported risk_tier {risk_tier!r}")
    split = str(payload.get("split") or "UNSPECIFIED").strip().upper()
    if split not in VALID_SPLITS:
        raise ValueError(f"line {line_number}: unsupported split {split!r}")
    return ReviewLabel(
        pair_ref=pair_ref,
        review_case_ref=review_case_ref,
        label=label,
        risk_tier=risk_tier,
        split=split,
    )


def _validate_field_set(
    payload: Any,
    allowed: set[str],
    optional: set[str],
    line_number: int,
    kind: str,
) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"line {line_number}: {kind} record must be an object")
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(
            f"line {line_number}: unsupported {kind} fields {unknown}; raw text/customer identifiers/PII are not allowed"
        )
    missing = sorted(field for field in allowed - optional if field not in payload)
    if missing:
        raise ValueError(f"line {line_number}: missing {kind} fields {missing}")


def _safe_ref(value: Any, field: str, line_number: int) -> str:
    text = str(value or "").strip()
    if not SAFE_REF.fullmatch(text):
        raise ValueError(f"line {line_number}: {field} must be a safe opaque reference")
    return text


def _threshold_grid(step: float) -> list[float]:
    values: list[float] = []
    current = 0.0
    while current < 100:
        values.append(round(current, 6))
        current += step
    if not values or values[-1] != 100.0:
        values.append(100.0)
    return values


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _round_or_none(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None else None


def _wilson_lower(successes: int, total: int, z: float = 1.959963984540054) -> float | None:
    if total <= 0:
        return None
    p = successes / total
    z2 = z * z
    denominator = 1 + z2 / total
    center = p + z2 / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * total)) / total)
    return max(0.0, (center - margin) / denominator)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Incident Correlation Shadow Calibration Report",
        "",
        f"Status: **{result['status']}**",
        f"Engine version: `{result.get('engine_version') or 'UNKNOWN'}`",
        "",
        "## Dataset",
        "",
        f"- Review rows: {result['review_rows']}",
        f"- Decisive rows: {result['decisive_rows']}",
        f"- SAME_INCIDENT: {result['same_incident_rows']}",
        f"- DIFFERENT_INCIDENT: {result['different_incident_rows']}",
        f"- INSUFFICIENT_EVIDENCE: {result['insufficient_evidence_rows']}",
        f"- Preferred analysis split: `{result['preferred_analysis_split']}`",
        "",
        "## Safety interpretation",
        "",
        "- `false_merge_count` is the primary precision-first risk signal.",
        "- `false_merge_high_critical` must remain zero for the existing Shadow safety floor.",
        "- Hard-veto and planned/ineligible relationships are always predicted as not-same by this evaluator.",
        "- Wilson lower bounds are reported so a perfect observed precision on a small sample is not treated as certainty.",
        "- Runtime scores and human labels are separate input files; reviewers cannot silently rewrite scores in the label file.",
        "- This harness does not promote a threshold automatically.",
        "",
        "## Candidate thresholds",
        "",
    ]
    zero = result.get("zero_false_merge_candidates", [])
    if zero:
        lines.extend([
            "Thresholds with zero observed false merges in the preferred split:",
            "",
            "| Threshold | Precision | Precision low95 | Recall | False splits |",
            "| ---: | ---: | ---: | ---: | ---: |",
        ])
        for row in zero[:15]:
            lines.append(
                f"| {row['threshold']} | {_blank(row['precision'])} | {_blank(row['precision_wilson_low95'])} | "
                f"{_blank(row['recall'])} | {row['false_split_count']} |"
            )
    else:
        lines.append("No threshold in the sweep achieved zero observed false merges with at least one true positive.")
    lines.extend([
        "",
        "## Promotion gate",
        "",
        result["promotion_reason"],
        "",
        "A runtime threshold change requires a separately reviewed decision and must remain Shadow-first. This report alone is not authorization to change customer behavior, operational incident state, root-cause status, or `production_send=blocked`.",
        "",
    ])
    return "\n".join(lines)


def _blank(value: Any) -> str:
    return "" if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate reviewed Incident Correlation Shadow relationship scores.")
    parser.add_argument("--scores", required=True, help="Immutable runtime score JSONL")
    parser.add_argument("--labels", required=True, help="Human review label JSONL")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--step", type=float, default=1.0, help="Threshold sweep step, default 1.0")
    args = parser.parse_args(argv)
    scored = load_scored_jsonl(args.scores)
    labels = load_labels_jsonl(args.labels)
    records = join_review_records(scored, labels)
    result = evaluate_records(records, step=args.step)
    result["inputs"] = {
        "scores_sha256": _sha256_file(args.scores),
        "labels_sha256": _sha256_file(args.labels),
    }
    outputs = write_outputs(result, args.output_dir)
    print(json.dumps({"status": result["status"], "outputs": outputs}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
