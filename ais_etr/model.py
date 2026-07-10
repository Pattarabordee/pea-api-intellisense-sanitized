from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any

import pandas as pd

from .schemas import MatchResult, OutageEvent, Prediction


QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
MIN_GROUP_ROWS = 5
DEFAULT_QUANTILES = {"q10": 20.0, "q25": 32.0, "q50": 45.0, "q75": 68.0, "q90": 95.0}


@dataclass(frozen=True)
class TrainingResult:
    model_version: str
    estimator: str
    status: str
    metrics: dict[str, Any]
    artifact_path: Path


def _version() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"baseline-quantile-{stamp}"


def _quantile_dict(series: pd.Series) -> dict[str, float]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return dict(DEFAULT_QUANTILES)
    result = {}
    for q in QUANTILES:
        result[f"q{int(q * 100):02d}"] = round(float(values.quantile(q)), 2)
    return result


def load_training_frame(
    event_file: str | Path,
    etr_files: list[str | Path] | tuple[str | Path, ...],
    distance_file: str | Path,
) -> pd.DataFrame:
    event_df = pd.read_excel(event_file, header=2, dtype=str)
    event_df["EventNumber"] = event_df["EventNumber"].astype(str)

    etr_frames = []
    for path in etr_files:
        df = pd.read_excel(path, header=2)
        df["source_file"] = Path(path).name
        etr_frames.append(df)
    etr_df = pd.concat(etr_frames, ignore_index=True)
    etr_df["EventID"] = etr_df["EventID"].astype(str)

    for column in ("เริ่มเหตุการณ์", "จ่ายไฟกลับคืนครั้งแรก"):
        etr_df[column] = pd.to_datetime(etr_df[column], errors="coerce")
    etr_df["target_etr_minutes"] = (
        etr_df["จ่ายไฟกลับคืนครั้งแรก"] - etr_df["เริ่มเหตุการณ์"]
    ).dt.total_seconds() / 60
    etr_df = etr_df[(etr_df["target_etr_minutes"] >= 0) & (etr_df["target_etr_minutes"] <= 24 * 60)]

    merged = event_df.merge(etr_df, left_on="EventNumber", right_on="EventID", how="inner")
    if Path(distance_file).exists():
        dist_df = pd.read_csv(distance_file, dtype={"OpDeviceGIStag": str})
        merged = merged.merge(dist_df, on="OpDeviceGIStag", how="left", suffixes=("", "_gis"))
    merged["Feeder"] = merged["Feeder"].astype(str).str.upper()
    merged["device_type_model"] = merged.get("OpDeviceType", "").fillna("Unknown").astype(str)
    merged["event_start"] = pd.to_datetime(merged["เริ่มเหตุการณ์"], errors="coerce")
    return merged


def fit_quantile_baseline(frame: pd.DataFrame) -> dict[str, Any]:
    target = "target_etr_minutes"
    model: dict[str, Any] = {
        "model_version": _version(),
        "estimator": "quantile_baseline",
        "global": _quantile_dict(frame[target]),
        "by_feeder": {},
        "by_device_type": {},
        "by_feeder_device": {},
        "row_count": int(len(frame)),
    }
    for feeder, group in frame.groupby("Feeder", dropna=True):
        if len(group) >= MIN_GROUP_ROWS:
            model["by_feeder"][str(feeder)] = {"n": int(len(group)), "q": _quantile_dict(group[target])}
    for dtype, group in frame.groupby("device_type_model", dropna=True):
        if len(group) >= MIN_GROUP_ROWS:
            model["by_device_type"][str(dtype)] = {"n": int(len(group)), "q": _quantile_dict(group[target])}
    for (feeder, dtype), group in frame.groupby(["Feeder", "device_type_model"], dropna=True):
        if len(group) >= MIN_GROUP_ROWS:
            key = f"{feeder}|{dtype}"
            model["by_feeder_device"][key] = {"n": int(len(group)), "q": _quantile_dict(group[target])}
    return model


def _row_prediction(model: dict[str, Any], feeder: str | None, device_type: str | None) -> dict[str, float]:
    if feeder and device_type:
        item = model.get("by_feeder_device", {}).get(f"{feeder}|{device_type}")
        if item:
            return item["q"]
    if feeder:
        item = model.get("by_feeder", {}).get(feeder)
        if item:
            return item["q"]
    if device_type:
        item = model.get("by_device_type", {}).get(device_type)
        if item:
            return item["q"]
    return model.get("global") or dict(DEFAULT_QUANTILES)


def evaluate_time_holdout(frame: pd.DataFrame) -> dict[str, Any]:
    frame = frame.dropna(subset=["event_start", "target_etr_minutes"]).sort_values("event_start")
    if len(frame) < 30:
        return {"status": "insufficient_data", "rows": int(len(frame))}
    split = max(1, int(len(frame) * 0.8))
    train, test = frame.iloc[:split], frame.iloc[split:]
    model = fit_quantile_baseline(train)
    preds = []
    for _, row in test.iterrows():
        preds.append(_row_prediction(model, str(row.get("Feeder")), str(row.get("device_type_model"))))
    pred_df = pd.DataFrame(preds)
    actual = pd.to_numeric(test["target_etr_minutes"], errors="coerce").reset_index(drop=True)
    mae = (pred_df["q50"] - actual).abs().mean()
    coverage = ((actual >= pred_df["q10"]) & (actual <= pred_df["q90"])).mean()
    status = "gate_pass" if mae <= 16 and 0.75 <= coverage <= 0.90 else "gate_fail"
    return {
        "status": status,
        "rows_train": int(len(train)),
        "rows_test": int(len(test)),
        "q50_mae_minutes": round(float(mae), 2),
        "q10_q90_coverage": round(float(coverage), 3),
        "gate": {"q50_mae_max": 16, "coverage_min": 0.75, "coverage_max": 0.90},
    }


def train_and_save(
    event_file: str | Path,
    etr_files: list[str | Path] | tuple[str | Path, ...],
    distance_file: str | Path,
    artifact_path: str | Path,
) -> TrainingResult:
    frame = load_training_frame(event_file, etr_files, distance_file)
    metrics = evaluate_time_holdout(frame)
    model = fit_quantile_baseline(frame)
    model["metrics"] = metrics
    runtime_path = Path(artifact_path)
    path = runtime_path.parent / "model_candidates" / f"{model['model_version']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return TrainingResult(
        model_version=model["model_version"],
        estimator=model["estimator"],
        status=metrics.get("status", "unknown"),
        metrics=metrics,
        artifact_path=path,
    )


def promote_model_candidate(
    candidate_path: str | Path,
    runtime_path: str | Path,
    *,
    approved_by: str,
) -> dict[str, Any]:
    candidate = Path(candidate_path)
    destination = Path(runtime_path)
    approver = str(approved_by or "").strip()
    if not approver:
        raise ValueError("approved_by is required")
    model = json.loads(candidate.read_text(encoding="utf-8"))
    metrics = model.get("metrics") or {}
    if metrics.get("status") != "gate_pass":
        raise ValueError("candidate model has not passed the evaluation gate")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copyfile(candidate, temporary)
    temporary.replace(destination)
    registry = destination.parent / "model_registry.jsonl"
    entry = {
        "model_version": model.get("model_version"),
        "candidate_path": str(candidate),
        "runtime_path": str(destination),
        "approved_by": approver,
        "metrics": metrics,
        "status": "promoted_shadow_candidate",
        "production_send": "blocked",
        "promoted_at": datetime.now(timezone.utc).isoformat(),
    }
    with registry.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


class EtrPredictor:
    def __init__(self, model: dict[str, Any]):
        self.model = model

    @classmethod
    def load(cls, path: str | Path) -> "EtrPredictor":
        model_path = Path(path)
        if not model_path.exists():
            return cls({"model_version": "default-untrained", "global": dict(DEFAULT_QUANTILES)})
        return cls(json.loads(model_path.read_text(encoding="utf-8")))

    def predict(self, event: OutageEvent, match_result: MatchResult) -> Prediction:
        q = _row_prediction(
            self.model,
            event.outage_device.feeder,
            event.outage_device.device_type,
        )
        risk = risk_level(q, match_result)
        return Prediction(
            etr_minutes_p50=float(q["q50"]),
            q25=float(q["q25"]),
            q75=float(q["q75"]),
            q10=float(q["q10"]),
            q90=float(q["q90"]),
            risk_level=risk,
            model_version=self.model.get("model_version", "default-untrained"),
        )


def risk_level(q: dict[str, float], match_result: MatchResult) -> str:
    width = float(q["q90"]) - float(q["q10"])
    p50 = float(q["q50"])
    if not match_result.matches or match_result.match_confidence < 0.5:
        return "HIGH"
    if p50 >= 120 or width >= 120:
        return "HIGH"
    if p50 >= 60 or width >= 60:
        return "MEDIUM"
    return "LOW"

