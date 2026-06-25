from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


DEFAULT_LINE_PARSER_MODEL_OUTPUT = "runtime/line_parser_shadow_model.json"
DEFAULT_LINE_PARSER_SPLIT_OUTPUT = "runtime/line_parser_training_splits.jsonl"
DEFAULT_LINE_PARSER_EVAL_OUTPUT = "runtime/line_parser_shadow_eval.csv"
DEFAULT_LINE_PARSER_REPORT_OUTPUT = "runtime/line_parser_shadow_model_report.md"
DEFAULT_LINE_PARSER_REVIEW_OUTPUT = "runtime/line_parser_shadow_review_queue.csv"

LABEL_EVENT = "event_candidate"
LABEL_NON_EVENT = "non_event"
LABEL_REVIEW = "needs_review"
MODEL_ROLE = "shadow_parser_candidate_classifier"
LABEL_POLICY = "weak_labels_from_current_parser_for_parser_training_only_not_customer_truth"

TOKEN_RE = re.compile(r"\[[A-Z_]+\]|[A-Za-z][A-Za-z0-9_/.-]{1,}|[0-9]{2,}|[\u0e00-\u0e7f]{2,}")
DEVICE_SIGNAL_RE = re.compile(
    r"\b[A-Z]{3}\d{2}(?:[A-Z]{1,3}[-/][A-Z0-9/.-]+)?\b|"
    r"\bTR\d{2}-\d+\b|"
    r"\b\d{2}-\d{6}\b",
    re.IGNORECASE,
)
FEEDER_SIGNAL_RE = re.compile(r"\b[A-Z]{3}\d{2}\b", re.IGNORECASE)
OUTAGE_SIGNAL_RE = re.compile(
    r"\b(?:alarm|cb|d/f|fault|lockout|operate|operated|outage|recloser|switch|trip|tripped)\b|"
    r"\u0e01\u0e23\u0e30\u0e41\u0e2a\u0e44\u0e1f\u0e1f\u0e49\u0e32\u0e02\u0e31\u0e14\u0e02\u0e49\u0e2d\u0e07|"
    r"\u0e44\u0e1f\u0e14\u0e31\u0e1a|"
    r"\u0e44\u0e1f\u0e15\u0e01|"
    r"\u0e44\u0e1f\u0e1f\u0e49\u0e32\u0e02\u0e31\u0e14\u0e02\u0e49\u0e2d\u0e07|"
    r"\u0e44\u0e1f\u0e0a\u0e47\u0e2d\u0e15|"
    r"\u0e44\u0e1f\u0e44\u0e21\u0e48\u0e04\u0e23\u0e1a\u0e40\u0e1f\u0e2a|"
    r"\u0e2a\u0e32\u0e22\u0e2b\u0e25\u0e38\u0e14",
    re.IGNORECASE,
)
TREE_MAINTENANCE_RE = re.compile(
    r"\u0e15\u0e31\u0e14\s*\u0e15\u0e49\u0e19\u0e44\u0e21\u0e49|"
    r"\u0e15\u0e31\u0e14\u0e41\u0e15\u0e48\u0e07.{0,40}\u0e15\u0e49\u0e19\u0e44\u0e21\u0e49|"
    r"\u0e15\u0e31\u0e14\u0e25\u0e34\u0e14\u0e23\u0e2d\u0e19.{0,40}\u0e15\u0e49\u0e19\u0e44\u0e21\u0e49|"
    r"\u0e25\u0e34\u0e14\u0e23\u0e2d\u0e19.{0,40}\u0e15\u0e49\u0e19\u0e44\u0e21\u0e49|"
    r"\u0e15\u0e31\u0e14.{0,40}\u0e41\u0e19\u0e27\u0e23\u0e30\u0e1a\u0e1a\u0e44\u0e1f\u0e1f\u0e49\u0e32",
    re.IGNORECASE,
)


def train_line_parser_shadow_model(
    source: str | Path,
    model_output: str | Path = DEFAULT_LINE_PARSER_MODEL_OUTPUT,
    split_output: str | Path = DEFAULT_LINE_PARSER_SPLIT_OUTPUT,
    eval_output: str | Path = DEFAULT_LINE_PARSER_EVAL_OUTPUT,
    markdown_output: str | Path = DEFAULT_LINE_PARSER_REPORT_OUTPUT,
    review_output: str | Path = DEFAULT_LINE_PARSER_REVIEW_OUTPUT,
    max_features: int = 4000,
    threshold: float = 0.5,
    seed: str = "line-parser-shadow-v1",
) -> dict[str, Any]:
    rows, source_count, excluded_tree_maintenance = _load_training_rows(Path(source), seed)
    labeled = [row for row in rows if row["weak_label"] in {LABEL_EVENT, LABEL_NON_EVENT}]
    review = [row for row in rows if row["weak_label"] == LABEL_REVIEW]
    train_rows = [row for row in labeled if row["split"] == "train"]
    labels_in_train = {row["weak_label"] for row in train_rows}
    if labels_in_train != {LABEL_EVENT, LABEL_NON_EVENT}:
        raise ValueError("LINE parser shadow training needs both event and non-event rows in train split")

    model = _fit_naive_bayes(train_rows, max_features=max_features, seed=seed)
    metrics = {
        split: _evaluate_rows([row for row in labeled if row["split"] == split], model, threshold)
        for split in ("train", "validation", "test")
    }
    metrics["all_labeled"] = _evaluate_rows(labeled, model, threshold)
    review_predictions = _predict_review_rows(review, model)

    result = {
        "status": "ok",
        "model_role": MODEL_ROLE,
        "mode": "shadow",
        "production_send": "blocked",
        "label_policy": LABEL_POLICY,
        "source": str(source),
        "rows_read": source_count,
        "rows_used": len(rows),
        "rows_excluded_tree_maintenance": excluded_tree_maintenance,
        "rows_labeled": len(labeled),
        "rows_review": len(review),
        "rows_train": sum(1 for row in labeled if row["split"] == "train"),
        "rows_validation": sum(1 for row in labeled if row["split"] == "validation"),
        "rows_test": sum(1 for row in labeled if row["split"] == "test"),
        "weak_label_counts": dict(sorted(Counter(row["weak_label"] for row in rows).items())),
        "model_output": str(model_output),
        "split_output": str(split_output),
        "eval_output": str(eval_output),
        "markdown_output": str(markdown_output),
        "review_output": str(review_output),
        "metrics": metrics,
    }

    model_payload = {
        **model,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "status": "shadow_trained",
        "mode": "shadow",
        "production_send": "blocked",
        "label_policy": LABEL_POLICY,
        "training_source": str(source),
        "training_summary": {
            key: result[key]
            for key in ("rows_read", "rows_used", "rows_excluded_tree_maintenance", "rows_labeled", "rows_review")
        },
        "metrics": metrics,
    }
    _write_json(model_output, model_payload)
    _write_split_audit(split_output, rows)
    _write_eval_csv(eval_output, metrics)
    _write_review_queue(review_output, review_predictions)
    _write_markdown_report(markdown_output, result, model_payload)
    return result


def _load_training_rows(source: Path, seed: str) -> tuple[list[dict[str, Any]], int, int]:
    rows: list[dict[str, Any]] = []
    source_count = 0
    excluded_tree_maintenance = 0
    with source.open(encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict):
                continue
            source_count += 1
            text = str(item.get("text_sanitized") or "")
            if _is_tree_maintenance_text(text):
                excluded_tree_maintenance += 1
                continue
            parser_status = str((item.get("parser_candidate") or {}).get("status") or "")
            signal_flags = _signal_flags(text)
            weak_label, label_source = _weak_label(parser_status, signal_flags)
            message_ref = str(item.get("message_ref") or item.get("message_id") or f"line-{line_no}")
            rows.append(
                {
                    "message_ref": message_ref,
                    "created": str(item.get("created") or ""),
                    "source_kind": str(item.get("source_kind") or item.get("source") or ""),
                    "consent_manifest_id": str(item.get("consent_manifest_id") or ""),
                    "redaction_flags": [str(flag) for flag in item.get("raw_redaction_flags") or []],
                    "parser_status": parser_status,
                    "weak_label": weak_label,
                    "label_source": label_source,
                    "split": "",
                    "text": text,
                    "text_length": len(text),
                    **signal_flags,
                }
            )
    _assign_splits(rows, seed)
    return rows, source_count, excluded_tree_maintenance


def _is_tree_maintenance_text(text: str) -> bool:
    return bool(TREE_MAINTENANCE_RE.search(text))


def _signal_flags(text: str) -> dict[str, bool]:
    return {
        "has_device_signal": bool(DEVICE_SIGNAL_RE.search(text)),
        "has_feeder_signal": bool(FEEDER_SIGNAL_RE.search(text)),
        "has_outage_signal": bool(OUTAGE_SIGNAL_RE.search(text)),
    }


def _weak_label(parser_status: str, signals: dict[str, bool]) -> tuple[str, str]:
    if parser_status == "parsed":
        return LABEL_EVENT, "current_parser_parsed"
    if signals["has_device_signal"] or signals["has_feeder_signal"] or signals["has_outage_signal"]:
        return LABEL_REVIEW, "unparsed_has_operational_signal"
    return LABEL_NON_EVENT, "unparsed_without_operational_signal"


def _assign_splits(rows: list[dict[str, Any]], seed: str) -> None:
    by_label: dict[str, list[dict[str, Any]]] = {LABEL_EVENT: [], LABEL_NON_EVENT: []}
    for row in rows:
        if row["weak_label"] in by_label:
            by_label[row["weak_label"]].append(row)
        else:
            row["split"] = "review"
    for label_rows in by_label.values():
        label_rows.sort(key=lambda row: _stable_float(seed, row["message_ref"]))
        count = len(label_rows)
        if count == 0:
            continue
        train_cut = max(1, int(count * 0.70))
        validation_cut = train_cut + (max(1, int(count * 0.15)) if count >= 3 else 0)
        if validation_cut >= count and count >= 3:
            validation_cut = count - 1
        for index, row in enumerate(label_rows):
            if index < train_cut:
                row["split"] = "train"
            elif index < validation_cut:
                row["split"] = "validation"
            else:
                row["split"] = "test"


def _fit_naive_bayes(rows: list[dict[str, Any]], max_features: int, seed: str) -> dict[str, Any]:
    class_doc_counts = Counter(row["weak_label"] for row in rows)
    feature_counts_by_class = {LABEL_EVENT: Counter(), LABEL_NON_EVENT: Counter()}
    for row in rows:
        label = row["weak_label"]
        for feature, value in _hashed_features(row["text"]).items():
            feature_counts_by_class[label][feature] += min(value, 3)

    selected = _select_features(feature_counts_by_class, max_features=max_features)
    vocabulary = set(selected)
    alpha = 1.0
    class_log_prior: dict[str, float] = {}
    feature_log_likelihood: dict[str, dict[str, float]] = {LABEL_EVENT: {}, LABEL_NON_EVENT: {}}
    unseen_log_likelihood: dict[str, float] = {}
    total_docs = sum(class_doc_counts.values())
    vocab_size = max(1, len(vocabulary))
    for label in (LABEL_EVENT, LABEL_NON_EVENT):
        class_log_prior[label] = math.log((class_doc_counts[label] + alpha) / (total_docs + 2 * alpha))
        total = sum(feature_counts_by_class[label][feature] for feature in vocabulary)
        denominator = total + alpha * vocab_size
        unseen_log_likelihood[label] = math.log(alpha / denominator)
        for feature in vocabulary:
            count = feature_counts_by_class[label][feature]
            feature_log_likelihood[label][feature] = math.log((count + alpha) / denominator)

    return {
        "model_version": "line-parser-shadow-nb-1",
        "model_role": MODEL_ROLE,
        "feature_encoding": "sha256_16_of_internal_parser_features",
        "seed": seed,
        "classes": [LABEL_NON_EVENT, LABEL_EVENT],
        "max_features": max_features,
        "vocabulary_size": len(vocabulary),
        "vocabulary": selected,
        "class_doc_counts": dict(class_doc_counts),
        "class_log_prior": class_log_prior,
        "feature_log_likelihood": feature_log_likelihood,
        "unseen_log_likelihood": unseen_log_likelihood,
    }


def _select_features(feature_counts_by_class: dict[str, Counter], max_features: int) -> list[str]:
    all_features = set(feature_counts_by_class[LABEL_EVENT]) | set(feature_counts_by_class[LABEL_NON_EVENT])
    event_total = sum(feature_counts_by_class[LABEL_EVENT].values()) + 1
    non_event_total = sum(feature_counts_by_class[LABEL_NON_EVENT].values()) + 1
    scored: list[tuple[float, str]] = []
    for feature in all_features:
        event_count = feature_counts_by_class[LABEL_EVENT][feature]
        non_event_count = feature_counts_by_class[LABEL_NON_EVENT][feature]
        total_count = event_count + non_event_count
        if total_count < 2:
            continue
        event_rate = (event_count + 1) / event_total
        non_event_rate = (non_event_count + 1) / non_event_total
        score = abs(math.log(event_rate / non_event_rate)) * math.log(total_count + 1)
        scored.append((score, feature))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [feature for _score, feature in scored[:max_features]]


def _predict_review_rows(rows: list[dict[str, Any]], model: dict[str, Any]) -> list[dict[str, Any]]:
    predictions = []
    for row in rows:
        probability = _predict_event_probability(row["text"], model)
        predictions.append(
            {
                "message_ref": row["message_ref"],
                "created": row["created"],
                "source_kind": row["source_kind"],
                "model_event_probability": round(probability, 6),
                "label_source": row["label_source"],
                "has_device_signal": str(row["has_device_signal"]).lower(),
                "has_feeder_signal": str(row["has_feeder_signal"]).lower(),
                "has_outage_signal": str(row["has_outage_signal"]).lower(),
                "text_length": row["text_length"],
                "text_sanitized_excerpt": _excerpt(row["text"]),
                "review_label": "",
                "review_device_id": "",
                "review_feeder": "",
                "review_event_time": "",
                "review_notes": "",
                "redaction_flags": "|".join(row["redaction_flags"]),
                "consent_manifest_id": row["consent_manifest_id"],
            }
        )
    predictions.sort(key=lambda item: (-float(item["model_event_probability"]), item["created"], item["message_ref"]))
    return predictions


def _excerpt(text: str, limit: int = 240) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def _evaluate_rows(rows: list[dict[str, Any]], model: dict[str, Any], threshold: float) -> dict[str, Any]:
    tp = fp = tn = fn = 0
    for row in rows:
        probability = _predict_event_probability(row["text"], model)
        predicted_event = probability >= threshold
        actual_event = row["weak_label"] == LABEL_EVENT
        if predicted_event and actual_event:
            tp += 1
        elif predicted_event and not actual_event:
            fp += 1
        elif not predicted_event and actual_event:
            fn += 1
        else:
            tn += 1
    total = tp + fp + tn + fn
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and precision + recall else None
    return {
        "rows": total,
        "accuracy": round((tp + tn) / total, 4) if total else None,
        "precision_event": round(precision, 4) if precision is not None else None,
        "recall_event": round(recall, 4) if recall is not None else None,
        "f1_event": round(f1, 4) if f1 is not None else None,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
    }


def _predict_event_probability(text: str, model: dict[str, Any]) -> float:
    features = _hashed_features(text)
    scores: dict[str, float] = {}
    vocabulary = set(model["vocabulary"])
    for label in (LABEL_NON_EVENT, LABEL_EVENT):
        score = float(model["class_log_prior"][label])
        unseen = float(model["unseen_log_likelihood"][label])
        likelihoods = model["feature_log_likelihood"][label]
        for feature, value in features.items():
            if feature not in vocabulary:
                continue
            score += min(value, 3) * float(likelihoods.get(feature, unseen))
        scores[label] = score
    diff = max(-50.0, min(50.0, scores[LABEL_EVENT] - scores[LABEL_NON_EVENT]))
    return 1.0 / (1.0 + math.exp(-diff))


def _hashed_features(text: str) -> Counter:
    return Counter({_feature_hash(feature): count for feature, count in _raw_features(text).items()})


def _raw_features(text: str) -> Counter:
    lowered = text.lower()
    features: Counter[str] = Counter()
    tokens = TOKEN_RE.findall(lowered)
    for token in tokens[:240]:
        if len(token) > 80:
            continue
        features[f"tok={token}"] += 1
    for marker in ("[phone_redacted]", "[url_redacted]", "[email_redacted]", "[person_name_redacted]", "[mention_redacted]"):
        if marker in lowered:
            features[f"marker={marker}"] += 1
    flags = _signal_flags(text)
    for key, enabled in flags.items():
        if enabled:
            features[f"signal={key}"] += 1
    length = len(text)
    if length <= 20:
        features["len=short"] += 1
    elif length <= 120:
        features["len=medium"] += 1
    else:
        features["len=long"] += 1
    compact = re.sub(r"\s+", " ", lowered)[:360]
    for index in range(max(0, len(compact) - 2)):
        chunk = compact[index : index + 3]
        if chunk.strip():
            features[f"c3={chunk}"] += 1
    return features


def _feature_hash(value: str) -> str:
    return "f_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _stable_float(seed: str, value: str) -> float:
    digest = hashlib.sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()[:12]
    return int(digest, 16) / float(0xFFFFFFFFFFFF)


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_split_audit(path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            audit = {
                key: row[key]
                for key in (
                    "message_ref",
                    "created",
                    "source_kind",
                    "consent_manifest_id",
                    "parser_status",
                    "weak_label",
                    "label_source",
                    "split",
                    "text_length",
                    "has_device_signal",
                    "has_feeder_signal",
                    "has_outage_signal",
                )
            }
            audit["redaction_flags"] = row["redaction_flags"]
            handle.write(json.dumps(audit, ensure_ascii=False, sort_keys=True) + "\n")


def _write_eval_csv(path: str | Path, metrics: dict[str, dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = ("split", "rows", "accuracy", "precision_event", "recall_event", "f1_event", "tp", "fp", "tn", "fn")
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for split, values in metrics.items():
            writer.writerow({"split": split, **values})


def _write_review_queue(path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = (
        "message_ref",
        "created",
        "source_kind",
        "model_event_probability",
        "label_source",
        "has_device_signal",
        "has_feeder_signal",
        "has_outage_signal",
        "text_length",
        "text_sanitized_excerpt",
        "review_label",
        "review_device_id",
        "review_feeder",
        "review_event_time",
        "review_notes",
        "redaction_flags",
        "consent_manifest_id",
    )
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown_report(path: str | Path, result: dict[str, Any], model: dict[str, Any]) -> None:
    lines = [
        "# LINE Parser Shadow Model Report",
        "",
        "Status: `shadow_trained`",
        "",
        "## Guardrails",
        "",
        "- Model role: `shadow_parser_candidate_classifier`",
        "- Label policy: `parser_training_only_not_customer_truth`",
        "- Mode: `shadow`",
        "- Production send: `blocked`",
        "- Feature vocabulary is hashed; report omits raw LINE text and raw token strings.",
        "- Review queue includes sanitized excerpts only; no raw sender, chat id, phone, email, URL, LINE id, or mention.",
        "",
        "## Rows",
        "",
        f"- Rows read: `{result['rows_read']}`",
        f"- Rows used after exclusions: `{result['rows_used']}`",
        f"- Tree-maintenance rows excluded: `{result['rows_excluded_tree_maintenance']}`",
        f"- Labeled rows: `{result['rows_labeled']}`",
        f"- Review rows: `{result['rows_review']}`",
        f"- Train: `{result['rows_train']}`",
        f"- Validation: `{result['rows_validation']}`",
        f"- Test: `{result['rows_test']}`",
        f"- Vocabulary size: `{model['vocabulary_size']}`",
        "",
        "## Metrics",
        "",
        "| Split | Rows | Accuracy | Precision event | Recall event | F1 event | TP | FP | TN | FN |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for split, metrics in result["metrics"].items():
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{split}`",
                    str(metrics["rows"]),
                    _fmt(metrics["accuracy"]),
                    _fmt(metrics["precision_event"]),
                    _fmt(metrics["recall_event"]),
                    _fmt(metrics["f1_event"]),
                    str(metrics["tp"]),
                    str(metrics["fp"]),
                    str(metrics["tn"]),
                    str(metrics["fn"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Outputs",
            "",
            f"- Model: `{result['model_output']}`",
            f"- Split audit: `{result['split_output']}`",
            f"- Evaluation CSV: `{result['eval_output']}`",
        f"- Review queue: `{result['review_output']}`",
        "",
        "Review labels: use `event`, `non_event`, `ignore`, or `needs_more_context` in `review_label`.",
        "",
        "LINE labels are weak parser labels. AIS outage/restore remains the only ETR truth lane.",
        "",
    ]
    )
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)
