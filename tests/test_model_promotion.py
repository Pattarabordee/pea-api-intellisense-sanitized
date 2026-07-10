import json
from pathlib import Path
import tempfile
import unittest

from ais_etr.model import promote_model_candidate


class ModelPromotionTests(unittest.TestCase):
    def test_gate_fail_candidate_cannot_overwrite_runtime_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate.json"
            runtime = root / "model_quantiles.json"
            candidate.write_text(json.dumps({"model_version": "bad", "metrics": {"status": "gate_fail"}}), encoding="utf-8")
            runtime.write_text('{"model_version":"current"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                promote_model_candidate(candidate, runtime, approved_by="owner")
            self.assertIn("current", runtime.read_text(encoding="utf-8"))

    def test_gate_pass_candidate_requires_approver_and_writes_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "candidate.json"
            runtime = root / "model_quantiles.json"
            candidate.write_text(json.dumps({"model_version": "good", "metrics": {"status": "gate_pass"}}), encoding="utf-8")
            with self.assertRaises(ValueError):
                promote_model_candidate(candidate, runtime, approved_by="")
            result = promote_model_candidate(candidate, runtime, approved_by="model-owner")
            self.assertEqual(result["production_send"], "blocked")
            self.assertTrue((root / "model_registry.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
