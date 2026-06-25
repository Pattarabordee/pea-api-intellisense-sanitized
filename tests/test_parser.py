import unittest

from ais_etr.parser import parse_webex_message


class ParserTests(unittest.TestCase):
    def test_parse_recloser_message(self):
        msg = {
            "id": "m1",
            "roomId": "r1",
            "created": "2026-06-17T10:00:00Z",
            "text": "ไฟดับ อ.พังโคน Recloser PFA02VR-101 trip เวลา 2026-06-17 09:55",
        }
        event = parse_webex_message(msg)
        self.assertIsNotNone(event)
        self.assertEqual(event.outage_device.device_id, "PFA02VR-101")
        self.assertEqual(event.outage_device.feeder, "PFA02")
        self.assertEqual(event.outage_device.device_type, "Recloser")
        self.assertEqual(event.district, "พังโคน")

    def test_parse_event_number_and_feeder_text(self):
        msg = {
            "id": "m4",
            "roomId": "r1",
            "created": "2026-06-17T10:00:00Z",
            "text": "EventNumber: 6846984046 หม้อแปลง 2147XF000000105 Operate Feeder PFA09",
        }
        event = parse_webex_message(msg)
        self.assertIsNotNone(event)
        self.assertEqual(event.parsed_fields["event_number"], "6846984046")
        self.assertEqual(event.outage_device.feeder, "PFA09")

    def test_parse_cb_message(self):
        msg = {
            "id": "m2",
            "roomId": "r1",
            "created": "2026-06-17T10:00:00Z",
            "text": "CB WDA05VB-01 operated outage วาริชภูมิ",
        }
        event = parse_webex_message(msg)
        self.assertIsNotNone(event)
        self.assertEqual(event.outage_device.device_type, "CB")
        self.assertEqual(event.outage_device.feeder, "WDA05")

    def test_ignore_plain_message(self):
        msg = {"id": "m3", "roomId": "r1", "text": "ประชุมทีมพรุ่งนี้"}
        self.assertIsNone(parse_webex_message(msg))

    def test_ignore_negative_outage_message(self):
        msg = {"id": "m5", "roomId": "r1", "text": "แจ้งเพื่อทราบ ไม่มีเหตุไฟดับในพื้นที่"}
        self.assertIsNone(parse_webex_message(msg))


    def test_room_context_supplies_real_webex_district(self):
        msg = {
            "id": "m6",
            "roomId": "r1",
            "created": "2026-06-17T10:00:00Z",
            "roomDistrict": "พังโคน",
            "text": "Recloser PFA02VR-101 trip outage",
        }
        event = parse_webex_message(msg)
        self.assertIsNotNone(event)
        self.assertEqual(event.district, "พังโคน")
        self.assertEqual(event.parsed_fields["district_source"], "room_context")
        self.assertEqual(event.parsed_fields["event_number_missing_reason"], "not_present_in_message")

    def test_event_time_uses_operation_row_before_telemetry_row(self):
        msg = {
            "id": "m7",
            "roomId": "r1",
            "created": "2026-05-28T18:19:14.393Z",
            "roomDistrict": "พังโคน",
            "text": (
                "PFA03VB-01 Trip เวลา: 08:18:42.310 AOJ: กฟส.พังโคน (M) "
                "Time                     Status               Description\n"
                "-----------------------  -------------------  ----------------------------------\n"
                "2026-05-29 01:18:51.533  [Normal] 111.2034 A  Current Phase A\n"
                "2026-05-29 08:18:42.310  Open                 Circuit Breaker Status\n"
                "2026-05-29 08:18:42.739  Operate              AUTO RECLOSE OPERATED (AR_OPERATE)\n"
                "2026-05-29 08:18:42.830  Close                Circuit Breaker Status"
            ),
        }
        event = parse_webex_message(msg)
        self.assertIsNotNone(event)
        self.assertEqual(event.event_time, "2026-05-29T08:18:42.310000")
        self.assertEqual(event.parsed_fields["event_time_source"], "operation_row")
        self.assertEqual(event.parsed_fields["webex_device_interruption_class"], "momentary_le_1m")
        self.assertEqual(event.parsed_fields["webex_open_close_minutes"], 0.01)

    def test_device_operation_state_marks_open_without_close_as_sustained_candidate(self):
        msg = {
            "id": "m8",
            "roomId": "r1",
            "created": "2026-05-13T03:31:15.887Z",
            "roomDistrict": "พังโคน",
            "text": (
                "WWA10VR-101 Trip เวลา: 10:30:06.503 AOJ: กฟส.วานรนิวาส (S)\n"
                "2026-05-13 10:30:06.452  Trip     EARTH FAULT DETECTED (EARTH_TRIP)\n"
                "2026-05-13 10:30:06.503  Open     Switch status"
            ),
        }
        event = parse_webex_message(msg)
        self.assertIsNotNone(event)
        self.assertEqual(event.parsed_fields["webex_device_interruption_class"], "sustained_candidate")
        self.assertIsNone(event.parsed_fields["webex_open_close_minutes"])

    def test_operation_state_handles_sanitized_one_line_table(self):
        msg = {
            "id": "m9",
            "roomId": "r1",
            "created": "2026-03-22T08:41:31.000Z",
            "roomDistrict": "เธเธณเธ•เธฒเธเธฅเนเธฒ",
            "text": (
                "SEK05VR-101 Trip Time Status Description "
                "2026-03-22 15:41:25.353 Trip PHASE C FAULT DETECTED "
                "2026-03-22 15:41:25.404 Open Switch status "
                "2026-03-22 15:41:30.425 Close Switch status"
            ),
        }
        event = parse_webex_message(msg, districts=("เธเธณเธ•เธฒเธเธฅเนเธฒ",))
        self.assertIsNotNone(event)
        self.assertEqual(event.event_time, "2026-03-22T15:41:25.353000")
        self.assertEqual(event.parsed_fields["webex_device_interruption_class"], "momentary_le_1m")
        self.assertEqual(event.parsed_fields["webex_open_close_minutes"], 0.08)


if __name__ == "__main__":
    unittest.main()
