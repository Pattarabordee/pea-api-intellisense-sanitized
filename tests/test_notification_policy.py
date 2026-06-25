import unittest

from ais_etr.notifier import build_notification_payload
from ais_etr.parser import parse_webex_message
from ais_etr.schemas import CustomerMatch, MatchResult, Prediction


class NotificationPolicyTests(unittest.TestCase):
    def test_momentary_webex_operation_is_review_only_without_active_ais_confirmation(self):
        event = parse_webex_message(
            {
                "id": "msg-1",
                "roomId": "room-1",
                "created": "2026-06-17T10:00:00Z",
                "text": (
                    "PFA02VR-101 Trip "
                    "2026-06-17 10:00:00.000 Open Switch status "
                    "2026-06-17 10:00:05.000 Close Switch status"
                ),
            }
        )
        self.assertIsNotNone(event)
        payload = build_notification_payload(
            event,
            _match_result("recloser", 0.95),
            _prediction(),
        )

        self.assertEqual(payload["shadow_policy"]["customer_facing_gate"], "review_only")
        self.assertEqual(
            payload["shadow_policy"]["reason"],
            "momentary_webex_operation_requires_active_ais_outage_confirmation",
        )
        self.assertTrue(payload["shadow_policy"]["requires_active_ais_confirmation"])

    def test_sustained_candidate_with_confident_match_is_shadow_etr_candidate(self):
        event = parse_webex_message(
            {
                "id": "msg-2",
                "roomId": "room-1",
                "created": "2026-06-17T10:00:00Z",
                "text": "PFA02VR-101 Trip 2026-06-17 10:00:00.000 Open Switch status",
            }
        )
        self.assertIsNotNone(event)
        payload = build_notification_payload(
            event,
            _match_result("recloser", 0.95),
            _prediction(),
        )

        self.assertEqual(payload["shadow_policy"]["customer_facing_gate"], "shadow_etr_candidate")
        self.assertEqual(
            payload["shadow_policy"]["reason"],
            "confident_protection_match_with_sustained_like_webex_state",
        )


def _match_result(level: str, confidence: float) -> MatchResult:
    return MatchResult(
        matches=(CustomerMatch(customer="AIS", peano="6101", feeder="PFA02", match_level=level),),
        match_level=level,
        match_confidence=confidence,
    )


def _prediction() -> Prediction:
    return Prediction(
        etr_minutes_p50=45,
        q25=30,
        q75=75,
        q10=20,
        q90=100,
        risk_level="MEDIUM",
        model_version="test-model",
    )


if __name__ == "__main__":
    unittest.main()
