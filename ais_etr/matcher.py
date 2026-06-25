from __future__ import annotations

from collections import OrderedDict
from typing import Iterable

from .schemas import CustomerAsset, CustomerMatch, MatchResult, OutageEvent
from .utils import normalize_device_id, normalize_feeder


MATCH_CONFIDENCE = {
    "cb": 0.95,
    "recloser": 0.9,
    "switch": 0.86,
    "transformer": 0.72,
    "feeder": 0.35,
}


class ProtectionMatcher:
    def __init__(self, assets: Iterable[CustomerAsset]):
        self.assets = [asset for asset in assets if asset.confidence_eligible]

    def match(self, event: OutageEvent) -> MatchResult:
        device_id = normalize_device_id(event.outage_device.device_id)
        feeder = normalize_feeder(event.outage_device.feeder)
        if device_id:
            for level, predicate in (
                ("cb", lambda asset: device_id in asset.cb_ids),
                ("recloser", lambda asset: device_id in asset.recloser_ids),
                ("switch", lambda asset: device_id in asset.switch_ids),
                (
                    "transformer",
                    lambda asset: device_id in {asset.transformer_id, asset.transformer_peano},
                ),
            ):
                matched = self._dedup(asset for asset in self.assets if predicate(asset))
                if matched:
                    return self._result(matched, level)

        if feeder:
            matched = self._dedup(asset for asset in self.assets if asset.feeder == feeder)
            if matched:
                return self._result(matched, "feeder")
        return MatchResult(matches=(), match_level=None, match_confidence=0.0)

    def _dedup(self, assets: Iterable[CustomerAsset]) -> list[CustomerAsset]:
        deduped: OrderedDict[str, CustomerAsset] = OrderedDict()
        for asset in assets:
            deduped.setdefault(asset.peano, asset)
        return list(deduped.values())

    def _result(self, assets: list[CustomerAsset], level: str) -> MatchResult:
        matches = tuple(
            CustomerMatch(
                customer=asset.customer,
                peano=asset.peano,
                feeder=asset.feeder,
                match_level=level,
            )
            for asset in assets
        )
        return MatchResult(
            matches=matches,
            match_level=level,
            match_confidence=MATCH_CONFIDENCE[level],
        )

