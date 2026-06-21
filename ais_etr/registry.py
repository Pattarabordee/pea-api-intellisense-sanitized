from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from .schemas import CustomerAsset
from .utils import first_present, normalize_device_id, normalize_feeder, split_device_list


REGISTRY_SHEET = "Upstream Trace"


def _clean_peano(value: object) -> str | None:
    text = first_present([value])
    if not text:
        return None
    return text.strip()


def load_assets_from_upstream_result(path: str | Path, customer: str = "AIS") -> list[CustomerAsset]:
    """Build AIS customer assets from the current upstream trace workbook."""
    df = pd.read_excel(path, sheet_name=REGISTRY_SHEET, dtype=str)
    assets: list[CustomerAsset] = []
    for _, row in df.iterrows():
        peano = _clean_peano(row.get("PEANO"))
        if not peano:
            continue
        status = first_present([row.get("สถานะ")])
        confidence_eligible = status == "OK"
        feeder = normalize_feeder(first_present([row.get("Feeder ID"), row.get("TX: Feeder")]))
        tx_id = normalize_device_id(row.get("TX: FACILITYID"))
        tx_peano = normalize_device_id(row.get("TX: PEANO"))
        assets.append(
            CustomerAsset(
                peano=peano,
                customer=customer,
                feeder=feeder,
                meter_location=first_present([row.get("สถานที่ Meter")]),
                transformer_id=tx_id,
                transformer_peano=tx_peano,
                recloser_ids=split_device_list(row.get("RC: FACILITYID")),
                switch_ids=split_device_list(row.get("SW: FACILITYID")),
                cb_ids=split_device_list(row.get("CB: FACILITYID")),
                trace_status=status,
                confidence_eligible=confidence_eligible,
            )
        )
    return dedupe_assets(assets)


def dedupe_assets(assets: Iterable[CustomerAsset]) -> list[CustomerAsset]:
    by_peano: dict[str, CustomerAsset] = {}
    for asset in assets:
        existing = by_peano.get(asset.peano)
        if existing is None or (asset.confidence_eligible and not existing.confidence_eligible):
            by_peano[asset.peano] = asset
    return list(by_peano.values())


def registry_summary(assets: Iterable[CustomerAsset]) -> dict[str, int]:
    assets = list(assets)
    return {
        "total_assets": len(assets),
        "confidence_eligible": sum(1 for asset in assets if asset.confidence_eligible),
        "no_meter_backlog": sum(1 for asset in assets if asset.trace_status == "NO_METER"),
        "with_recloser": sum(1 for asset in assets if asset.recloser_ids),
        "with_switch": sum(1 for asset in assets if asset.switch_ids),
        "with_cb": sum(1 for asset in assets if asset.cb_ids),
    }

