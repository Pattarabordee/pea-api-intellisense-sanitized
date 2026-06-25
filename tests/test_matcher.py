import unittest

from ais_etr.matcher import ProtectionMatcher
from ais_etr.schemas import CustomerAsset, OutageDevice, OutageEvent


def event(device_type="Recloser", device_id="PFA02VR-101", feeder="PFA02"):
    return OutageEvent(
        event_id="e1",
        source="webex",
        webex_message_id="m1",
        room_id="r1",
        raw_text="",
        outage_device=OutageDevice(device_type=device_type, device_id=device_id, feeder=feeder),
    )


class MatcherTests(unittest.TestCase):
    def setUp(self):
        self.assets = [
            CustomerAsset(
                peano="6101",
                feeder="PFA02",
                transformer_id="49-100001",
                recloser_ids=("PFA02VR-101",),
                switch_ids=("PFA02VF-01",),
                cb_ids=("PFA02VB-01",),
                trace_status="OK",
                confidence_eligible=True,
            ),
            CustomerAsset(
                peano="6102",
                feeder="PFA02",
                recloser_ids=("PFA02VR-101",),
                trace_status="OK",
                confidence_eligible=True,
            ),
            CustomerAsset(
                peano="NOPE",
                feeder="PFA02",
                recloser_ids=("PFA02VR-101",),
                trace_status="NO_METER",
                confidence_eligible=False,
            ),
        ]

    def test_exact_recloser_match_excludes_no_meter(self):
        result = ProtectionMatcher(self.assets).match(event())
        self.assertEqual(result.match_level, "recloser")
        self.assertEqual({m.peano for m in result.matches}, {"6101", "6102"})

    def test_feeder_fallback(self):
        result = ProtectionMatcher(self.assets).match(event("Unknown", None, "PFA02"))
        self.assertEqual(result.match_level, "feeder")
        self.assertLess(result.match_confidence, 0.5)

    def test_no_match(self):
        result = ProtectionMatcher(self.assets).match(event("Switch", "WDA05VF-01", "WDA05"))
        self.assertFalse(result.matches)


if __name__ == "__main__":
    unittest.main()

