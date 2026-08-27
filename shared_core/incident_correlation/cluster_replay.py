from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

OBS_SCHEMA_VERSION = "incident-correlation-cluster-observation.v1"
TRUTH_SCHEMA_VERSION = "incident-correlation-cluster-truth.v1"
REPORT_SCHEMA_VERSION = "incident-correlation-cluster-replay-report.v1"

_ALLOWED_TRANSITIONS = {
    "NONE",
    "NEW",
    "UNCHANGED",
    "ADD_SINGLETON",
    "EXPAND",
    "MERGE",
    "SPLIT",
    "CLOSE",
    "REOPEN",
}
_ALLOWED_LINEAGE = {"MERGE", "SPLIT", "RECURRENCE", "RELATED"}
_ALLOWED_RISK = {"NORMAL", "HIGH", "CRITICAL"}
_ALLOWED_SPLITS = {"CALIBRATION", "EVALUATION", "UNSPECIFIED"}

_OBS_FIELDS = {
    "schema_version",
    "scenario_ref",
    "step_index",
    "engine_version",
    "active_report_refs",
    "observed_partition",
    "observed_transition",
    "observed_lineage_types",
}
_TRUTH_FIELDS = {
    "schema_version",
    "scenario_ref",
    "step_index",
    "review_case_ref",
    "active_report_refs",
    "expected_partition",
    "expected_transition",
    "expected_lineage_types",
    "risk_tier",
    "split",
}


@dataclass(frozen=True)
class ClusterObservation:
    scenario_ref: str
    step_index: int
    engine_version: str
    active_report_refs: tuple[str, ...]
    observed_partition: tuple[tuple[str, ...], ...]
    observed_transition: str
    observed_lineage_types: tuple[str, ...]


@dataclass(frozen=True)
class ClusterTruth:
    scenario_ref: str
    step_index: int
    review_case_ref: str
    active_report_refs: tuple[str, ...]
    expected_partition: tuple[tuple[str, ...], ...]
    expected_transition: str
    expected_lineage_types: tuple[str, ...]
    risk_tier: str
    split: str


@dataclass(frozen=True)
class ReplayStep:
    observation: ClusterObservation
    truth: ClusterTruth


@dataclass(frozen=True)
class StepMetrics:
    scenario_ref: str
    step_index: int
    review_case_ref: str
    split: str
    risk_tier: str
    active_reports: int
    expected_clusters: int
    observed_clusters: int
    truth_related_pairs: int
    observed_related_pairs: int
    true_merge_pairs: int
    false_merge_pairs: int
    false_split_pairs: int
    pair_precision: float | None
    pair_recall: float | None
    pair_f1: float | None
    exact_partition_match: bool
    expected_transition: str
    observed_transition: str
    transition_match: bool
    lineage_match: bool
    high_critical_false_merge: bool


def load_observations_jsonl(path: str | Path) -> list[ClusterObservation]:
    rows = _load_jsonl(path)
    output: list[ClusterObservation] = []
    seen: set[tuple[str, int]] = set()
    versions: set[str] = set()
    for line_no, payload in rows:
        _validate_fields(payload, _OBS_FIELDS, line_no, "observation")
        if payload["schema_version"] != OBS_SCHEMA_VERSION:
            raise ValueError(f"line {line_no}: unsupported observation schema_version")
        scenario_ref = _opaque_ref(payload["scenario_ref"], "scenario_ref", line_no)
        step_index = _nonnegative_int(payload["step_index"], "step_index", line_no)
        key = (scenario_ref, step_index)
        if key in seen:
            raise ValueError(f"line {line_no}: duplicate observation key {key}")
        seen.add(key)
        engine_version = _required_text(payload["engine_version"], "engine_version", line_no)
        versions.add(engine_version)
        active = _report_refs(payload["active_report_refs"], "active_report_refs", line_no)
        partition = _partition(payload["observed_partition"], active, "observed_partition", line_no)
        transition = _enum(payload["observed_transition"], _ALLOWED_TRANSITIONS, "observed_transition", line_no)
        lineage = _enum_list(payload["observed_lineage_types"], _ALLOWED_LINEAGE, "observed_lineage_types", line_no)
        output.append(
            ClusterObservation(
                scenario_ref=scenario_ref,
                step_index=step_index,
                engine_version=engine_version,
                active_report_refs=active,
                observed_partition=partition,
                observed_transition=transition,
                observed_lineage_types=lineage,
            )
        )
    if len(versions) > 1:
        raise ValueError("mixed engine_version values are not allowed in one replay run")
    _validate_scenario_steps(output)
    return sorted(output, key=lambda x: (x.scenario_ref, x.step_index))


def load_truth_jsonl(path: str | Path) -> list[ClusterTruth]:
    rows = _load_jsonl(path)
    output: list[ClusterTruth] = []
    seen: set[tuple[str, int]] = set()
    for line_no, payload in rows:
        _validate_fields(payload, _TRUTH_FIELDS, line_no, "truth")
        if payload["schema_version"] != TRUTH_SCHEMA_VERSION:
            raise ValueError(f"line {line_no}: unsupported truth schema_version")
        scenario_ref = _opaque_ref(payload["scenario_ref"], "scenario_ref", line_no)
        step_index = _nonnegative_int(payload["step_index"], "step_index", line_no)
        key = (scenario_ref, step_index)
        if key in seen:
            raise ValueError(f"line {line_no}: duplicate truth key {key}")
        seen.add(key)
        review_case_ref = _opaque_ref(payload["review_case_ref"], "review_case_ref", line_no)
        active = _report_refs(payload["active_report_refs"], "active_report_refs", line_no)
        partition = _partition(payload["expected_partition"], active, "expected_partition", line_no)
        transition = _enum(payload["expected_transition"], _ALLOWED_TRANSITIONS, "expected_transition", line_no)
        lineage = _enum_list(payload["expected_lineage_types"], _ALLOWED_LINEAGE, "expected_lineage_types", line_no)
        risk_tier = _enum(payload["risk_tier"], _ALLOWED_RISK, "risk_tier", line_no)
        split = _enum(payload["split"], _ALLOWED_SPLITS, "split", line_no)
        output.append(
            ClusterTruth(
                scenario_ref=scenario_ref,
                step_index=step_index,
                review_case_ref=review_case_ref,
                active_report_refs=active,
                expected_partition=partition,
                expected_transition=transition,
                expected_lineage_types=lineage,
                risk_tier=risk_tier,
                split=split,
            )
        )
    _validate_case_split_integrity(output)
    _validate_scenario_steps(output)
    return sorted(output, key=lambda x: (x.scenario_ref, x.step_index))


def join_replay(observations: Iterable[ClusterObservation], truths: Iterable[ClusterTruth]) -> list[ReplayStep]:
    obs = {(x.scenario_ref, x.step_index): x for x in observations}
    truth = {(x.scenario_ref, x.step_index): x for x in truths}
    missing_obs = sorted(set(truth) - set(obs))
    extra_obs = sorted(set(obs) - set(truth))
    if missing_obs:
        raise ValueError(f"truth rows without runtime observations: {missing_obs[:10]}")
    if extra_obs:
        raise ValueError(f"runtime observations without reviewed truth: {extra_obs[:10]}")
    result: list[ReplayStep] = []
    for key in sorted(obs):
        observation = obs[key]
        expected = truth[key]
        if observation.active_report_refs != expected.active_report_refs:
            raise ValueError(f"active_report_refs mismatch at {key}")
        result.append(ReplayStep(observation=observation, truth=expected))
    return result


def evaluate_step(step: ReplayStep) -> StepMetrics:
    observed_pairs = _related_pairs(step.observation.observed_partition)
    truth_pairs = _related_pairs(step.truth.expected_partition)
    tp = len(observed_pairs & truth_pairs)
    fp = len(observed_pairs - truth_pairs)
    fn = len(truth_pairs - observed_pairs)
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = _f1(precision, recall)
    exact = _normalized_partition(step.observation.observed_partition) == _normalized_partition(step.truth.expected_partition)
    transition_match = step.observation.observed_transition == step.truth.expected_transition
    lineage_match = set(step.observation.observed_lineage_types) == set(step.truth.expected_lineage_types)
    return StepMetrics(
        scenario_ref=step.truth.scenario_ref,
        step_index=step.truth.step_index,
        review_case_ref=step.truth.review_case_ref,
        split=step.truth.split,
        risk_tier=step.truth.risk_tier,
        active_reports=len(step.truth.active_report_refs),
        expected_clusters=len(step.truth.expected_partition),
        observed_clusters=len(step.observation.observed_partition),
        truth_related_pairs=len(truth_pairs),
        observed_related_pairs=len(observed_pairs),
        true_merge_pairs=tp,
        false_merge_pairs=fp,
        false_split_pairs=fn,
        pair_precision=precision,
        pair_recall=recall,
        pair_f1=f1,
        exact_partition_match=exact,
        expected_transition=step.truth.expected_transition,
        observed_transition=step.observation.observed_transition,
        transition_match=transition_match,
        lineage_match=lineage_match,
        high_critical_false_merge=(step.truth.risk_tier in {"HIGH", "CRITICAL"} and fp > 0),
    )


def evaluate_replay(steps: Iterable[ReplayStep]) -> dict[str, Any]:
    items = list(steps)
    metrics = [evaluate_step(step) for step in items]
    engine_versions = sorted({step.observation.engine_version for step in items})
    engine_version = engine_versions[0] if len(engine_versions) == 1 else ""
    by_split = {split: [m for m in metrics if m.split == split] for split in _ALLOWED_SPLITS}
    preferred = "EVALUATION" if by_split["EVALUATION"] else ("CALIBRATION" if by_split["CALIBRATION"] else "ALL")
    selected = metrics if preferred == "ALL" else by_split[preferred]
    transition_gaps = _transition_gaps(metrics)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "NO_REVIEWED_DATA" if not metrics else "REPLAY_EVALUATED",
        "engine_version": engine_version,
        "steps": [asdict(m) for m in metrics],
        "summary_all": _aggregate(metrics),
        "summary_by_split": {k: _aggregate(v) for k, v in sorted(by_split.items())},
        "preferred_analysis_split": preferred,
        "preferred_summary": _aggregate(selected),
        "transition_gaps": transition_gaps,
        "runtime_threshold_changed": False,
        "automatic_promotion": False,
        "known_runtime_gap": (
            "Current Shadow worker schema supports REOPENED lifecycle, but no time-based QUIET/CLOSED/REOPENED state machine "
            "was observed in the Phase-2 worker implementation reviewed for this harness. Expected REOPEN scenarios should "
            "therefore remain explicit acceptance gaps until lifecycle logic exists and is replay-tested."
        ),
    }


def write_outputs(result: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "incident_correlation_cluster_replay_summary.json"
    steps_path = out / "incident_correlation_cluster_replay_steps.csv"
    report_path = out / "incident_correlation_cluster_replay_report.md"
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = result.get("steps", [])
    columns = list(asdict(_empty_metrics()).keys())
    with steps_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})
    report_path.write_text(_render_markdown(result), encoding="utf-8")
    return {"summary": str(summary_path), "steps": str(steps_path), "report": str(report_path)}


def _aggregate(metrics: list[StepMetrics]) -> dict[str, Any]:
    tp = sum(m.true_merge_pairs for m in metrics)
    fp = sum(m.false_merge_pairs for m in metrics)
    fn = sum(m.false_split_pairs for m in metrics)
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    return {
        "steps": len(metrics),
        "pair_precision": precision,
        "pair_precision_wilson_low95": _wilson_low(tp, tp + fp),
        "pair_recall": recall,
        "pair_recall_wilson_low95": _wilson_low(tp, tp + fn),
        "pair_f1": _f1(precision, recall),
        "false_merge_pairs": fp,
        "false_split_pairs": fn,
        "high_critical_false_merge_steps": sum(1 for m in metrics if m.high_critical_false_merge),
        "exact_partition_matches": sum(1 for m in metrics if m.exact_partition_match),
        "exact_partition_rate": _ratio(sum(1 for m in metrics if m.exact_partition_match), len(metrics)),
        "transition_matches": sum(1 for m in metrics if m.transition_match),
        "transition_accuracy": _ratio(sum(1 for m in metrics if m.transition_match), len(metrics)),
        "lineage_matches": sum(1 for m in metrics if m.lineage_match),
        "lineage_accuracy": _ratio(sum(1 for m in metrics if m.lineage_match), len(metrics)),
        "hard_safety_pass": (fp == 0 and not any(m.high_critical_false_merge for m in metrics)) if metrics else None,
    }


def _transition_gaps(metrics: list[StepMetrics]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for m in metrics:
        if not m.transition_match or not m.lineage_match:
            gaps.append(
                {
                    "scenario_ref": m.scenario_ref,
                    "step_index": m.step_index,
                    "expected_transition": m.expected_transition,
                    "observed_transition": m.observed_transition,
                    "transition_match": m.transition_match,
                    "lineage_match": m.lineage_match,
                    "risk_tier": m.risk_tier,
                }
            )
    return gaps


def _render_markdown(result: dict[str, Any]) -> str:
    s = result["preferred_summary"]
    lines = [
        "# Incident Correlation Cluster Replay v1",
        "",
        "Shadow-only evaluation of runtime cluster partitions and transitions against reviewed truth.",
        "",
        "## Preferred evaluation summary",
        "",
        f"- Analysis split: {result['preferred_analysis_split']}",
        f"- Steps: {s['steps']}",
        f"- Pair precision: {_fmt(s['pair_precision'])}",
        f"- Pair recall: {_fmt(s['pair_recall'])}",
        f"- Pair F1: {_fmt(s['pair_f1'])}",
        f"- False-merge pairs: {s['false_merge_pairs']}",
        f"- False-split pairs: {s['false_split_pairs']}",
        f"- High/Critical false-merge steps: {s['high_critical_false_merge_steps']}",
        f"- Exact partition rate: {_fmt(s['exact_partition_rate'])}",
        f"- Transition accuracy: {_fmt(s['transition_accuracy'])}",
        f"- Lineage accuracy: {_fmt(s['lineage_accuracy'])}",
        f"- Hard safety pass: {s['hard_safety_pass']}",
        "",
        "## Transition gaps",
        "",
    ]
    gaps = result.get("transition_gaps", [])
    if not gaps:
        lines.append("No reviewed transition gaps in this replay set.")
    else:
        lines += ["| Scenario | Step | Expected | Observed | Risk |", "| --- | ---: | --- | --- | --- |"]
        for row in gaps:
            lines.append(
                f"| {row['scenario_ref']} | {row['step_index']} | {row['expected_transition']} | "
                f"{row['observed_transition']} | {row['risk_tier']} |"
            )
    lines += [
        "",
        "## Guardrails",
        "",
        "- Cluster IDs are intentionally ignored; evaluation compares partitions of opaque report refs.",
        "- Singletons must be present in each partition, preventing hidden dropped reports.",
        "- CALIBRATION/EVALUATION split leakage is rejected at review_case_ref level.",
        "- Runtime thresholds are not changed and no promotion is automatic.",
        f"- Known runtime gap: {result['known_runtime_gap']}",
        "",
    ]
    return "\n".join(lines)


def _related_pairs(partition: tuple[tuple[str, ...], ...]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for cluster in partition:
        for i in range(len(cluster)):
            for j in range(i + 1, len(cluster)):
                pairs.add((cluster[i], cluster[j]))
    return pairs


def _normalized_partition(partition: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(sorted(tuple(sorted(cluster)) for cluster in partition))


def _partition(value: Any, active: tuple[str, ...], field: str, line_no: int) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list):
        raise ValueError(f"line {line_no}: {field} must be an array of arrays")
    clusters: list[tuple[str, ...]] = []
    seen: set[str] = set()
    for cluster in value:
        if not isinstance(cluster, list) or not cluster:
            raise ValueError(f"line {line_no}: every {field} cluster must be a non-empty array")
        refs = tuple(sorted(_opaque_ref(x, field, line_no) for x in cluster))
        if len(set(refs)) != len(refs):
            raise ValueError(f"line {line_no}: duplicate report ref inside {field}")
        overlap = seen.intersection(refs)
        if overlap:
            raise ValueError(f"line {line_no}: report ref appears in multiple {field} clusters")
        seen.update(refs)
        clusters.append(refs)
    if seen != set(active):
        raise ValueError(f"line {line_no}: {field} must partition active_report_refs exactly, including singletons")
    return _normalized_partition(tuple(clusters))


def _report_refs(value: Any, field: str, line_no: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"line {line_no}: {field} must be an array")
    refs = tuple(sorted(_opaque_ref(x, field, line_no) for x in value))
    if len(set(refs)) != len(refs):
        raise ValueError(f"line {line_no}: duplicate value in {field}")
    return refs


def _opaque_ref(value: Any, field: str, line_no: int) -> str:
    text = _required_text(value, field, line_no)
    if len(text) > 128 or any(ch.isspace() for ch in text):
        raise ValueError(f"line {line_no}: {field} must be a compact opaque ref")
    return text


def _required_text(value: Any, field: str, line_no: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"line {line_no}: {field} is required")
    return value.strip()


def _nonnegative_int(value: Any, field: str, line_no: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"line {line_no}: {field} must be a non-negative integer")
    return value


def _enum(value: Any, allowed: set[str], field: str, line_no: int) -> str:
    text = _required_text(value, field, line_no).upper()
    if text not in allowed:
        raise ValueError(f"line {line_no}: invalid {field}: {text}")
    return text


def _enum_list(value: Any, allowed: set[str], field: str, line_no: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"line {line_no}: {field} must be an array")
    items = tuple(sorted({_enum(x, allowed, field, line_no) for x in value}))
    return items


def _validate_fields(payload: Any, expected: set[str], line_no: int, kind: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"line {line_no}: {kind} row must be an object")
    keys = set(payload)
    missing = expected - keys
    extra = keys - expected
    if missing:
        raise ValueError(f"line {line_no}: missing {kind} fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"line {line_no}: unknown {kind} fields rejected: {sorted(extra)}")


def _validate_scenario_steps(rows: Iterable[Any]) -> None:
    by_scenario: dict[str, list[int]] = {}
    for row in rows:
        by_scenario.setdefault(row.scenario_ref, []).append(row.step_index)
    for scenario, steps in sorted(by_scenario.items()):
        ordered = sorted(steps)
        expected = list(range(len(ordered)))
        if ordered != expected:
            raise ValueError(f"scenario {scenario} step_index must be contiguous from 0; got {ordered}")


def _validate_case_split_integrity(rows: Iterable[ClusterTruth]) -> None:
    by_case: dict[str, set[str]] = {}
    for row in rows:
        if row.split == "UNSPECIFIED":
            continue
        by_case.setdefault(row.review_case_ref, set()).add(row.split)
    leaked = sorted(k for k, splits in by_case.items() if len(splits) > 1)
    if leaked:
        raise ValueError("review_case_ref leakage across CALIBRATION/EVALUATION splits is not allowed: " + ", ".join(leaked[:10]))


def _load_jsonl(path: str | Path) -> list[tuple[int, Any]]:
    rows: list[tuple[int, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            rows.append((line_no, json.loads(line)))
    return rows


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _wilson_low(successes: int, total: int, z: float = 1.959963984540054) -> float | None:
    if total <= 0:
        return None
    p = successes / total
    denom = 1 + z * z / total
    center = p + z * z / (2 * total)
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (center - radius) / denom)


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def _empty_metrics() -> StepMetrics:
    return StepMetrics("", 0, "", "", "", 0, 0, 0, 0, 0, 0, 0, 0, None, None, None, False, "NONE", "NONE", False, False, False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Incident Correlation cluster partitions and lifecycle transitions in Shadow mode")
    parser.add_argument("--observations", required=True)
    parser.add_argument("--truth", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    observations = load_observations_jsonl(args.observations)
    truth = load_truth_jsonl(args.truth)
    steps = join_replay(observations, truth)
    result = evaluate_replay(steps)
    result["inputs"] = {
        "observations_sha256": _sha256_file(args.observations),
        "truth_sha256": _sha256_file(args.truth),
    }
    outputs = write_outputs(result, args.output_dir)
    print(json.dumps({"status": result["status"], "outputs": outputs}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
