from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / "runtime" / name).read_text(encoding="utf-8")


class RuntimeMeterStateReleaseGuardTests(unittest.TestCase):
    def test_production_gate_uses_v2_meter_state_metrics_not_strict_identity(self):
        text = _read("production_gate_live_snapshot.ps1")

        self.assertIn('Metric-Int $metrics "v2_model_ready_rows"', text)
        self.assertIn('Metric-Int $metrics "model_ready_clean_truth_rows"', text)
        self.assertIn('mapping_version=$mappingVersion, model_ready=$modelReadyRows, v2_model_ready=$v2ModelReadyRows', text)
        self.assertIn("meter_state_truth_alignment", text)
        self.assertNotIn("truth_strict_identity_intervals", text)


    def test_open_interval_review_hashes_references_and_omits_request_and_last4_values(self):
        text = _read("open_interval_review.ps1")

        self.assertIn("interval_ref = Safe-Text $item.interval_ref", text)
        self.assertNotIn("$item.interval_id", text)
        self.assertNotIn("$item.outage_request_id", text)
        self.assertNotIn("$item.restore_request_id", text)
        self.assertNotIn("$item.meter.last4", text)
        self.assertNotIn("$item.site.last4", text)
