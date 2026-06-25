from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "build_ne_pea_office_locations.py"
SPEC = importlib.util.spec_from_file_location("build_ne_pea_office_locations", MODULE_PATH)
ne_locations = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ne_locations
SPEC.loader.exec_module(ne_locations)


class NePeaOfficeLocationTests(unittest.TestCase):
    def test_address_parser_handles_king_district_after_abbreviation(self):
        parts = ne_locations.extract_address_parts(
            "70 ม.9 ต.โพนแพง อ.กิ่งอำเภอรัตนวาปี จ.หนองคาย 43120"
        )

        self.assertEqual(parts["subdistrict"], "โพนแพง")
        self.assertEqual(parts["district"], "รัตนวาปี")
        self.assertEqual(parts["province"], "หนองคาย")

    def test_longdo_match_rejects_cross_province_candidate(self):
        office = ne_locations.ListedOffice(
            office_id="x",
            source_section="p41",
            office_name="การไฟฟ้าส่วนภูมิภาคอำเภอนายูง",
            office_type="branch",
            province_hint="อุดรธานี",
            info_center_url="https://example.test",
            official_address="247 ม.7 ต.บ้านก้อง อ.นายูง จ.อุดรธานี 41380",
            phone="",
            list_source="test",
        )
        poi = ne_locations.LongdoPoi(
            poi_id="A00000000",
            page=1,
            name="การไฟฟ้าส่วนภูมิภาค สำนักงานการไฟฟ้าส่วนภูมิภาคสาขาอำเภองาว",
            desc="อ.งาว จ.ลำปาง Thailand",
        )

        self.assertEqual(ne_locations.longdo_match_score(office, poi), -1)

    def test_classify_numbered_city_office_as_branch(self):
        self.assertEqual(
            ne_locations.classify_office("การไฟฟ้าจังหวัดอุดรธานี 2 (นิตโย)"),
            "branch",
        )


if __name__ == "__main__":
    unittest.main()
