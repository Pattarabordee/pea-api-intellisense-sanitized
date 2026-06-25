from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "ais_site_pea_road_distance.py"
SPEC = importlib.util.spec_from_file_location("ais_site_pea_road_distance", MODULE_PATH)
road_distance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = road_distance
SPEC.loader.exec_module(road_distance)


class AisSitePeaRoadDistanceTests(unittest.TestCase):
    def test_extract_longdo_lat_lon_from_snippet_meta_url(self):
        html = '<meta property="og:image" content="https://map.longdo.com/snippet/?lat=17.338325397&long=101.755317362&zoom=16">'
        self.assertEqual(
            road_distance.extract_longdo_lat_lon(html),
            (17.338325397, 101.755317362),
        )

    def test_official_match_uses_office_name_not_address(self):
        request = road_distance.parse_requested_offices(["กฟส.ภูเขียว"])[0]
        records = [
            road_distance.OfficialOfficeRecord(
                name="การไฟฟ้าส่วนภูมิภาคอำเภอแก้งคร้อ",
                address="ต.ช่องสามหมอ อ.แก้งคร้อ จ.ชัยภูมิ ถนนชัยภูมิ-ภูเขียว",
                phone="",
                province_class="p36",
            ),
            road_distance.OfficialOfficeRecord(
                name="การไฟฟ้าส่วนภูมิภาคอำเภอภูเขียว",
                address="336 ม.1 ต.หนองตูม อ.ภูเขียว จ.ชัยภูมิ 36110",
                phone="",
                province_class="p36",
            ),
        ]

        official, score = road_distance.match_official_record(request, records)

        self.assertGreater(score, 0)
        self.assertEqual(official.name, "การไฟฟ้าส่วนภูมิภาคอำเภอภูเขียว")

    def test_official_match_supports_city_number_alias(self):
        request = road_distance.parse_requested_offices(["กฟส.เมืองนครราชสีมา2(หัวทะเล)"])[0]
        records = [
            road_distance.OfficialOfficeRecord(
                name="การไฟฟ้าส่วนภูมิภาคจังหวัดนครราชสีมา 2 (หัวทะเล)",
                address="69 ม.1 ต.พะเนา อ.เมืองนครราชสีมา จ.นครราชสีมา 30000",
                phone="",
                province_class="p30",
            )
        ]

        official, score = road_distance.match_official_record(request, records)

        self.assertGreater(score, 0)
        self.assertEqual(official.name, "การไฟฟ้าส่วนภูมิภาคจังหวัดนครราชสีมา 2 (หัวทะเล)")

    def test_select_nearest_office_ignores_null_osrm_cells(self):
        site = road_distance.Site(
            site_ref="site-a",
            site_code="",
            company="AWN",
            source_province="ขอนแก่น",
            lat=16.4,
            lon=102.8,
        )
        offices = [
            road_distance.Office(
                office_id="pea_01",
                requested_office="กฟจ.ขอนแก่น (L)",
                size="L",
                branch="ขอนแก่น",
                official_name="",
                official_address="",
                phone="",
                lat=16.43,
                lon=102.83,
                coordinate_source="longdo",
                coordinate_url="https://example.test/a",
                coordinate_status="test",
            ),
            road_distance.Office(
                office_id="pea_02",
                requested_office="กฟส.บ้านไผ่ (M)",
                size="M",
                branch="บ้านไผ่",
                official_name="",
                official_address="",
                phone="",
                lat=16.05,
                lon=102.73,
                coordinate_source="longdo",
                coordinate_url="https://example.test/b",
                coordinate_status="test",
            ),
        ]

        nearest = road_distance.select_nearest_office(
            [None, 12500.0],
            [None, 900.0],
            site,
            offices,
        )

        self.assertEqual(nearest["nearest_office_id"], "pea_02")
        self.assertEqual(nearest["road_distance_km"], 12.5)
        self.assertEqual(nearest["osrm_duration_min"], 15.0)
        self.assertEqual(nearest["route_status"], "ok")


if __name__ == "__main__":
    unittest.main()
