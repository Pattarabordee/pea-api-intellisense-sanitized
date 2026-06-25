import tempfile
import unittest
from pathlib import Path

import pandas as pd

from ais_etr.registry import load_assets_from_upstream_result, registry_summary


class RegistryTests(unittest.TestCase):
    def test_load_assets_and_backlog(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "upstream.xlsx"
            df = pd.DataFrame(
                [
                    {
                        "PEANO": "6101",
                        "Feeder ID": "PFA02",
                        "TX: FACILITYID": "49-1",
                        "TX: PEANO": "TR49-1",
                        "RC: FACILITYID": "PFA02VR-101",
                        "SW: FACILITYID": "PFA02VF-01 | PFA02VF-02",
                        "CB: FACILITYID": "PFA02VB-01",
                        "สถานะ": "OK",
                    },
                    {"PEANO": "6102", "สถานะ": "NO_METER"},
                ]
            )
            with pd.ExcelWriter(path) as writer:
                df.to_excel(writer, sheet_name="Upstream Trace", index=False)
            assets = load_assets_from_upstream_result(path)
            self.assertEqual(len(assets), 2)
            summary = registry_summary(assets)
            self.assertEqual(summary["confidence_eligible"], 1)
            self.assertEqual(summary["no_meter_backlog"], 1)
            self.assertEqual(assets[0].switch_ids, ("PFA02VF-01", "PFA02VF-02"))


if __name__ == "__main__":
    unittest.main()

