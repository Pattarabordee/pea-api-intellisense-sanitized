from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


PEA_INFO_CENTER_URL = "https://www.pea.co.th/pea-information-center"
PEA_SERVICE_URL = "https://www.pea.co.th/about-pea/pea-service"
PEA_OFFICE_SEARCH_URL = "https://sbiz.pea.co.th/pea-office/search.php"
LONGDO_POI_URL = "https://map.longdo.com/poilist/248?page={page}"
LONGDO_INFO_URL = "https://map.longdo.com/main/p/{poi_id}/info"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"

DEFAULT_INFO_CENTER_CACHE = Path("runtime/pea_information_center.html")
DEFAULT_OFFICE_SEARCH_CACHE = Path("runtime/pea_office_search_cache.html")
DEFAULT_LONGDO_LIST_CACHE = Path("runtime/longdo_pea_poi_pages_cache.json")
DEFAULT_LONGDO_COORD_CACHE = Path("runtime/ne_pea_longdo_coord_cache.json")
DEFAULT_NOMINATIM_CACHE = Path("runtime/ne_pea_nominatim_cache.json")
DEFAULT_SEED_COORDINATES = Path("runtime/pea_office_coordinate_sources.csv")
DEFAULT_OUTPUT = Path("runtime/ne_pea_office_locations.csv")
DEFAULT_SQLITE = Path("runtime/ne_pea_office_locations.sqlite")
DEFAULT_SUMMARY = Path("runtime/ne_pea_office_locations_summary.md")

NE_SECTION_TITLES = [
    "เขต 1 (ภาคตะวันออกเฉียงเหนือ)",
    "เขต 2 (ภาคตะวันออกเฉียงเหนือ)",
    "เขต 3 (ภาคตะวันออกเฉียงเหนือ)",
]

EXPECTED_COUNTS = {
    "provincial": 20,
    "branch": 132,
    "sub_branch": 189,
}

THAI_PROVINCES_NE = [
    "กาฬสินธุ์",
    "ขอนแก่น",
    "ชัยภูมิ",
    "นครพนม",
    "นครราชสีมา",
    "บึงกาฬ",
    "บุรีรัมย์",
    "มหาสารคาม",
    "มุกดาหาร",
    "ยโสธร",
    "ร้อยเอ็ด",
    "เลย",
    "ศรีสะเกษ",
    "สกลนคร",
    "สุรินทร์",
    "หนองคาย",
    "หนองบัวลำภู",
    "อำนาจเจริญ",
    "อุดรธานี",
    "อุบลราชธานี",
]

NE_PROVINCE_CLASSES = {f"p{idx}" for idx in range(30, 50)}
NE_ENGLISH_PROVINCES = [
    "Kalasin",
    "Khon Kaen",
    "Chaiyaphum",
    "Nakhon Phanom",
    "Nakhon Ratchasima",
    "Bueng Kan",
    "Buri Ram",
    "Buriram",
    "Maha Sarakham",
    "Mukdahan",
    "Yasothon",
    "Roi Et",
    "Loei",
    "Si Sa Ket",
    "Sisaket",
    "Sakon Nakhon",
    "Surin",
    "Nong Khai",
    "Nong Bua Lamphu",
    "Amnat Charoen",
    "Udon Thani",
    "Ubon Ratchathani",
]


@dataclass(frozen=True)
class ListedOffice:
    office_id: str
    source_section: str
    office_name: str
    office_type: str
    province_hint: str
    info_center_url: str
    official_address: str
    phone: str
    list_source: str


@dataclass(frozen=True)
class LongdoPoi:
    poi_id: str
    page: int
    name: str
    desc: str


def fetch_text(url: str, timeout: int = 45) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 AIS-PEA-office-location/1.0",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def load_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = unescape(str(value)).replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_thai(value: object) -> str:
    text = clean_text(value)
    return re.sub(r"[\s\.\-_/()๏ผ๏ผ]+", "", text)


def strip_pea_prefix(name: str) -> str:
    text = clean_text(name)
    text = re.sub(r"^PEA\s*", "", text, flags=re.I)
    text = re.sub(r"^การไฟฟ้าส่วนภูมิภาค\s*", "", text)
    text = text.replace("สาขาอำเภออขุขันธ์", "สาขาอำเภอขุขันธ์")
    return clean_text(text)


def classify_office(name: str) -> str:
    stripped = strip_pea_prefix(name)
    if stripped.startswith("เขต ") or ("เขต" in stripped and "ภาค" in stripped):
        return "regional"
    if re.search(r"จังหวัด.+\d", stripped):
        return "branch"
    if stripped.startswith("จังหวัด"):
        return "provincial"
    if stripped.startswith("สาขาย่อย"):
        return "sub_branch"
    if stripped.startswith("ตำบล") or stripped.startswith("บ้าน"):
        return "sub_branch"
    return "branch"


def infer_province_hint(name: str) -> str:
    text = strip_pea_prefix(name)
    for province in THAI_PROVINCES_NE:
        if province in text:
            return province
    return ""


def extract_section(html: str, title: str, next_titles: list[str]) -> str:
    marker = f'data-title="{title}"'
    start = html.find(marker)
    if start < 0:
        raise ValueError(f"PEA Info Center section not found: {title}")
    end = len(html)
    for next_title in next_titles:
        idx = html.find(f'data-title="{next_title}"', start + len(marker))
        if idx >= 0:
            end = min(end, idx)
    return html[start:end]


def parse_info_center_offices(html: str) -> list[ListedOffice]:
    all_titles = NE_SECTION_TITLES + ["เขต 1 (ภาคกลาง)"]
    offices: list[ListedOffice] = []
    seen: set[tuple[str, str]] = set()
    for section_index, title in enumerate(NE_SECTION_TITLES):
        next_titles = all_titles[section_index + 1 :]
        section = extract_section(html, title, next_titles)
        links = re.findall(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', section, flags=re.S)
        for href, label_html in links:
            label = clean_text(label_html)
            if not label.startswith("PEA "):
                continue
            office_type = classify_office(label)
            if office_type == "regional":
                continue
            key = (normalize_thai(label), href.strip())
            if key in seen:
                continue
            seen.add(key)
            offices.append(
                ListedOffice(
                    office_id=f"ne_pea_{len(offices) + 1:03d}",
                    source_section=title,
                    office_name=label,
                    office_type=office_type,
                    province_hint=infer_province_hint(label),
                    info_center_url=href.strip(),
                    official_address="",
                    phone="",
                    list_source="pea_information_center",
                )
            )
    return offices


def parse_pea_office_search_records(html: str) -> list[dict[str, str]]:
    panel_re = re.compile(
        r'<div class="col-md-6 province (?P<province_class>[^"]+)">.*?'
        r'<div class="panel-body">(?P<body>.*?)</div></div></div>',
        re.S,
    )
    paragraph_re = re.compile(r"<p>(.*?)</p>", re.S)
    records: list[dict[str, str]] = []
    for panel in panel_re.finditer(html):
        parts = [clean_text(part) for part in paragraph_re.findall(panel.group("body"))]
        parts = [part for part in parts if part]
        if not parts:
            continue
        phone = ""
        address_parts: list[str] = []
        for part in parts[1:]:
            if part.startswith("โทร"):
                phone = part
            else:
                address_parts.append(part)
        records.append(
            {
                "province_class": panel.group("province_class"),
                "name": parts[0],
                "address": clean_text(" ".join(address_parts)),
                "phone": phone,
            }
        )
    return records


def load_office_search_html(cache_path: Path, refresh: bool) -> str:
    if cache_path.exists() and not refresh:
        return cache_path.read_text(encoding="utf-8", errors="replace")
    html = fetch_text(PEA_OFFICE_SEARCH_URL)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(html, encoding="utf-8")
    return html


def parse_official_ne_offices(html: str) -> list[ListedOffice]:
    records = parse_pea_office_search_records(html)
    offices: list[ListedOffice] = []
    seen: set[str] = set()
    for record in records:
        if record["province_class"] not in NE_PROVINCE_CLASSES:
            continue
        office_type = classify_office(record["name"])
        if office_type == "regional":
            continue
        key = normalize_thai(f"{record['name']} {record['address']}")
        if key in seen:
            continue
        seen.add(key)
        offices.append(
            ListedOffice(
                office_id=f"ne_pea_{len(offices) + 1:03d}",
                source_section=record["province_class"],
                office_name=record["name"],
                office_type=office_type,
                province_hint=infer_province_hint(record["address"] or record["name"]),
                info_center_url=PEA_OFFICE_SEARCH_URL,
                official_address=record["address"],
                phone=record["phone"],
                list_source="pea_office_search",
            )
        )
    return offices


def load_info_center_html(cache_path: Path, refresh: bool) -> str:
    if cache_path.exists() and not refresh:
        return cache_path.read_text(encoding="utf-8", errors="replace")
    html = fetch_text(PEA_INFO_CENTER_URL)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(html, encoding="utf-8")
    return html


def iter_cached_longdo_pois(cache_path: Path) -> list[LongdoPoi]:
    payload = load_json(cache_path, {})
    pois: list[LongdoPoi] = []
    if not isinstance(payload, dict):
        return pois
    for page_text, page_payload in payload.items():
        if not isinstance(page_payload, dict):
            continue
        try:
            page = int(page_text)
        except ValueError:
            page = 0
        for entry in page_payload.get("entries", []):
            if not isinstance(entry, dict):
                continue
            poi_id = clean_text(entry.get("id"))
            if not poi_id:
                continue
            pois.append(
                LongdoPoi(
                    poi_id=poi_id,
                    page=page,
                    name=clean_text(entry.get("name")),
                    desc=clean_text(entry.get("desc")),
                )
            )
    return pois


def extract_longdo_listing_entries(html: str, page: int) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for match in re.finditer(r'href="https://map\.longdo\.com/main/p/(A[0-9]+)/info"[^>]*>(.*?)</a>', html, re.S):
        poi_id = match.group(1)
        name = clean_text(match.group(2))
        start = max(0, match.start() - 500)
        end = min(len(html), match.end() + 2500)
        snippet = clean_text(html[start:end])
        entries.append({"page": page, "id": poi_id, "name": name, "desc": snippet})
    return entries


def refresh_longdo_listing_cache(cache_path: Path, start_page: int, end_page: int, sleep_seconds: float) -> None:
    cache = load_json(cache_path, {})
    if not isinstance(cache, dict):
        cache = {}
    for page in range(start_page, end_page + 1):
        page_key = str(page)
        if page_key in cache:
            continue
        html = fetch_text(LONGDO_POI_URL.format(page=page), timeout=45)
        cache[page_key] = {"entries": extract_longdo_listing_entries(html, page)}
        write_json(cache_path, cache)
        if sleep_seconds:
            time.sleep(sleep_seconds)


def office_search_terms(office: ListedOffice) -> list[str]:
    stripped = strip_pea_prefix(office.office_name)
    terms = [stripped]
    terms.append(stripped.replace("สาขาอำเภอ", "อำเภอ"))
    terms.append(stripped.replace("กิ่งอำเภอ", "อำเภอ"))
    terms.append(stripped.replace("สาขาย่อยอำเภอ", "สาขาย่อยอำเภอ"))
    terms.append(stripped.replace("สาขาย่อยตำบล", "สาขาย่อยตำบล"))
    terms.append(stripped.replace("จังหวัด", "จังหวัด"))
    address_parts = extract_address_parts(office.official_address)
    district = address_parts.get("district", "")
    subdistrict = address_parts.get("subdistrict", "")
    province = address_parts.get("province", "")
    if district:
        terms.append(f"อำเภอ{district}")
        terms.append(f"สาขาอำเภอ{district}")
        terms.append(f"สาขาย่อยอำเภอ{district}")
    if subdistrict:
        terms.append(f"ตำบล{subdistrict}")
        terms.append(f"สาขาย่อยตำบล{subdistrict}")
    if province and office.office_type == "provincial":
        terms.append(f"จังหวัด{province}")
    return [term for idx, term in enumerate(terms) if term and term not in terms[:idx]]


def longdo_match_score(office: ListedOffice, poi: LongdoPoi) -> int:
    haystack = normalize_thai(f"{poi.name} {poi.desc}")
    score = -1
    if normalize_thai("เขต") in haystack and office.office_type != "regional":
        return -1
    if office.province_hint and normalize_thai(office.province_hint) not in haystack:
        return -1
    address_parts = extract_address_parts(office.official_address)
    district = address_parts.get("district", "")
    if office.office_type in {"branch", "sub_branch"} and district and normalize_thai(district) not in haystack:
        return -1
    if office.office_type == "provincial":
        for branch_marker in ["อำเภอ", "สาขา", "สาขาย่อย"]:
            if normalize_thai(branch_marker) in haystack:
                return -1

    for term in office_search_terms(office):
        needle = normalize_thai(term)
        if not needle:
            continue
        if needle in haystack:
            score = max(score, 100 + len(needle))
        compact = needle.replace(normalize_thai("สาขาอำเภอ"), normalize_thai("อำเภอ"))
        compact = compact.replace(normalize_thai("สาขาย่อยอำเภอ"), normalize_thai("สาขาย่อยอำเภอ"))
        if compact and compact in haystack:
            score = max(score, 80 + len(compact))

    if office.office_type == "provincial" and normalize_thai("จังหวัด") not in haystack:
        score -= 35
    if office.office_type == "sub_branch" and normalize_thai("สาขาย่อย") not in haystack:
        score -= 35
    if office.office_type == "branch" and normalize_thai("สาขาย่อย") in haystack:
        score -= 20
    if office.province_hint and normalize_thai(office.province_hint) not in haystack:
        score -= 15
    return score


def match_longdo_poi(office: ListedOffice, pois: list[LongdoPoi]) -> tuple[LongdoPoi | None, int]:
    scored = [(longdo_match_score(office, poi), poi) for poi in pois]
    scored = [(score, poi) for score, poi in scored if score >= 60]
    if not scored:
        return None, -1
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1], scored[0][0]


def extract_longdo_lat_lon(html: str) -> tuple[float, float] | None:
    match = re.search(r"snippet/\?lat=([-0-9.]+)&(?:long|lon)=([-0-9.]+)", html)
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def fetch_longdo_coordinate(poi: LongdoPoi, cache: dict[str, object]) -> tuple[float | None, float | None, str]:
    if poi.poi_id in cache:
        item = cache[poi.poi_id]
        if isinstance(item, dict):
            lat = item.get("lat")
            lon = item.get("lon")
            status = clean_text(item.get("status")) or "cached"
            if lat is not None and lon is not None:
                return float(lat), float(lon), status
            return None, None, status
    html = fetch_text(LONGDO_INFO_URL.format(poi_id=poi.poi_id), timeout=45)
    coords = extract_longdo_lat_lon(html)
    if coords is None:
        cache[poi.poi_id] = {"status": "longdo_no_coordinate"}
        return None, None, "longdo_no_coordinate"
    lat, lon = coords
    cache[poi.poi_id] = {"lat": lat, "lon": lon, "status": "fetched"}
    return lat, lon, "fetched"


def nominatim_query(office: ListedOffice) -> str:
    stripped = strip_pea_prefix(office.office_name)
    return f"การไฟฟ้าส่วนภูมิภาค {stripped} ประเทศไทย"


def extract_address_parts(address: str) -> dict[str, str]:
    text = clean_text(address)
    parts: dict[str, str] = {}
    subdistrict = re.search(r"(?:^|\s)ต\.?([^\s]+)", text)
    district = re.search(r"(?:^|\s)(?:อ\.|อำเภอ|กิ่งอำเภอ)([^\s]+)", text)
    province = re.search(r"(?:^|\s)จ\.?([^\s]+)", text)
    if subdistrict:
        parts["subdistrict"] = clean_text(subdistrict.group(1))
    if district:
        district_text = clean_text(district.group(1))
        district_text = re.sub(r"^(กิ่งอำเภอ|อำเภอ)", "", district_text)
        parts["district"] = clean_text(district_text)
    if province:
        parts["province"] = clean_text(province.group(1))
    return parts


def extract_district_from_office_name(name: str) -> str:
    stripped = strip_pea_prefix(name)
    match = re.search(r"(?:กิ่งอำเภอ|อำเภอ)([^\s]+)", stripped)
    if match:
        return clean_text(match.group(1))
    return ""


def nominatim_queries(office: ListedOffice) -> list[tuple[str, str]]:
    stripped = strip_pea_prefix(office.office_name)
    parts = extract_address_parts(office.official_address)
    subdistrict = parts.get("subdistrict", "")
    district = parts.get("district", "") or extract_district_from_office_name(office.office_name)
    office_district = extract_district_from_office_name(office.office_name)
    province = parts.get("province", office.province_hint)
    queries: list[tuple[str, str]] = [
        ("name", f"การไฟฟ้าส่วนภูมิภาค {stripped} ประเทศไทย"),
    ]
    if subdistrict and district and province:
        queries.append(("admin_subdistrict", f"{subdistrict} {district} {province} ประเทศไทย"))
    if district and province:
        queries.append(("admin_district", f"{district} {province} ประเทศไทย"))
    if office_district and office_district != district and province:
        queries.append(("office_district", f"{office_district} {province} ประเทศไทย"))
    if office_district:
        queries.append(("office_district_any_province", f"{office_district} ประเทศไทย"))
    return [(kind, query) for kind, query in queries if query.strip()]


def fetch_nominatim_coordinate(
    office: ListedOffice,
    cache: dict[str, object],
    sleep_seconds: float,
) -> tuple[float | None, float | None, str, str]:
    last_status = "nominatim_no_match"
    last_url = ""
    for kind, query in nominatim_queries(office):
        if query in cache:
            item = cache[query]
        else:
            params = {
                "q": query,
                "format": "jsonv2",
                "limit": "1",
                "countrycodes": "th",
            }
            url = f"{NOMINATIM_SEARCH_URL}?{urllib.parse.urlencode(params)}"
            try:
                text = fetch_text(url, timeout=45)
                item = {"url": url, "payload": json.loads(text), "kind": kind}
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                item = {"error": str(exc), "kind": kind}
            cache[query] = item
            if sleep_seconds:
                time.sleep(sleep_seconds)

        if not isinstance(item, dict):
            last_status = "nominatim_bad_cache"
            continue
        payload = item.get("payload")
        last_url = clean_text(item.get("url"))
        if isinstance(payload, list) and payload:
            first = payload[0]
            try:
                status = "nominatim_fetched" if kind == "name" else f"nominatim_{kind}_fallback"
                return float(first["lat"]), float(first["lon"]), status, last_url
            except (KeyError, TypeError, ValueError):
                last_status = "nominatim_invalid_payload"
    return None, None, last_status, last_url


def seed_coordinate_key(name: str, address: str) -> str:
    return normalize_thai(f"{name} {address}")


def load_seed_coordinates(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    seeds: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = clean_text(row.get("official_office_name"))
            address = clean_text(row.get("official_address"))
            lat = clean_text(row.get("office_lat"))
            lon = clean_text(row.get("office_lon"))
            if not name or not lat or not lon:
                continue
            key = seed_coordinate_key(name, address)
            seeds[key] = {
                "lat": lat,
                "lon": lon,
                "source": clean_text(row.get("coordinate_source")),
                "url": clean_text(row.get("coordinate_url")),
            }
    return seeds


def build_rows(
    offices: list[ListedOffice],
    pois: list[LongdoPoi],
    longdo_coord_cache_path: Path,
    nominatim_cache_path: Path,
    seed_coordinates_path: Path,
    sleep_seconds: float,
) -> list[dict[str, object]]:
    longdo_coord_cache = load_json(longdo_coord_cache_path, {})
    if not isinstance(longdo_coord_cache, dict):
        longdo_coord_cache = {}
    nominatim_cache = load_json(nominatim_cache_path, {})
    if not isinstance(nominatim_cache, dict):
        nominatim_cache = {}
    seed_coordinates = load_seed_coordinates(seed_coordinates_path)

    rows: list[dict[str, object]] = []
    for office in offices:
        matched_poi, match_score = match_longdo_poi(office, pois)
        lat: float | None = None
        lon: float | None = None
        coord_status = ""
        source_url = ""
        source_name = ""
        longdo_id = ""
        longdo_page: int | str = ""
        match_name = ""
        match_desc = ""
        confidence = "review"
        seed = seed_coordinates.get(seed_coordinate_key(office.office_name, office.official_address))
        if seed:
            lat = float(seed["lat"])
            lon = float(seed["lon"])
            coord_status = "seeded_from_prior_verified_office_table"
            source_name = clean_text(seed.get("source")) or "seed"
            source_url = clean_text(seed.get("url"))
            confidence = "high"

        if lat is None and matched_poi is not None:
            longdo_id = matched_poi.poi_id
            longdo_page = matched_poi.page
            match_name = matched_poi.name
            match_desc = matched_poi.desc
            source_name = "longdo"
            source_url = LONGDO_INFO_URL.format(poi_id=matched_poi.poi_id)
            lat, lon, coord_status = fetch_longdo_coordinate(matched_poi, longdo_coord_cache)
            if lat is not None and lon is not None:
                confidence = "high" if match_score >= 100 else "medium"

        if lat is None or lon is None:
            n_lat, n_lon, n_status, n_url = fetch_nominatim_coordinate(office, nominatim_cache, sleep_seconds)
            if n_lat is not None and n_lon is not None:
                lat, lon = n_lat, n_lon
                coord_status = n_status
                source_name = "nominatim"
                source_url = n_url
                confidence = "low"
            else:
                coord_status = coord_status or n_status

        rows.append(
            {
                "office_id": office.office_id,
                "office_name": office.office_name,
                "office_type": office.office_type,
                "source_section": office.source_section,
                "province_hint": office.province_hint,
                "official_address": office.official_address,
                "phone": office.phone,
                "list_source": office.list_source,
                "lat": "" if lat is None else round(lat, 7),
                "lon": "" if lon is None else round(lon, 7),
                "coordinate_source": source_name,
                "coordinate_url": source_url,
                "coordinate_status": coord_status,
                "confidence": confidence,
                "info_center_url": office.info_center_url,
                "longdo_id": longdo_id,
                "longdo_page": longdo_page,
                "longdo_match_score": match_score if matched_poi is not None else "",
                "longdo_match_name": match_name,
                "longdo_match_desc": match_desc,
            }
        )
        write_json(longdo_coord_cache_path, longdo_coord_cache)
        write_json(nominatim_cache_path, nominatim_cache)
        if matched_poi is not None and sleep_seconds:
            time.sleep(sleep_seconds)
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "office_id",
        "office_name",
        "office_type",
        "source_section",
        "province_hint",
        "official_address",
        "phone",
        "list_source",
        "lat",
        "lon",
        "coordinate_source",
        "coordinate_url",
        "coordinate_status",
        "confidence",
        "info_center_url",
        "longdo_id",
        "longdo_page",
        "longdo_match_score",
        "longdo_match_name",
        "longdo_match_desc",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_sqlite(path: Path, rows: list[dict[str, object]], metadata: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE IF EXISTS ne_pea_office_locations")
        conn.execute("DROP TABLE IF EXISTS run_metadata")
        conn.execute(
            """
            CREATE TABLE ne_pea_office_locations (
                office_id TEXT PRIMARY KEY,
                office_name TEXT,
                office_type TEXT,
                source_section TEXT,
                province_hint TEXT,
                official_address TEXT,
                phone TEXT,
                list_source TEXT,
                lat REAL,
                lon REAL,
                coordinate_source TEXT,
                coordinate_url TEXT,
                coordinate_status TEXT,
                confidence TEXT,
                info_center_url TEXT,
                longdo_id TEXT,
                longdo_page INTEGER,
                longdo_match_score INTEGER,
                longdo_match_name TEXT,
                longdo_match_desc TEXT
            )
            """
        )
        conn.execute("CREATE TABLE run_metadata (key TEXT PRIMARY KEY, value TEXT)")
        if rows:
            keys = list(rows[0].keys())
            conn.executemany(
                f"INSERT INTO ne_pea_office_locations VALUES ({','.join(['?'] * len(keys))})",
                [[row[key] if row[key] != "" else None for key in keys] for row in rows],
            )
        conn.executemany(
            "INSERT INTO run_metadata VALUES (?,?)",
            [(str(key), json.dumps(value, ensure_ascii=False)) for key, value in metadata.items()],
        )
        conn.commit()


def counts_by(rows: list[dict[str, object]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field) or "")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def write_summary(path: Path, rows: list[dict[str, object]], metadata: dict[str, object]) -> None:
    counts_type = counts_by(rows, "office_type")
    counts_source = counts_by(rows, "coordinate_source")
    counts_conf = counts_by(rows, "confidence")
    missing_coords = [row for row in rows if row["lat"] == "" or row["lon"] == ""]
    review_rows = [row for row in rows if row["confidence"] != "high"]
    lines = [
        "# PEA office locations in Northeastern Thailand",
        "",
        f"- Generated: {metadata['generated_at']}",
        f"- Office list source: {metadata['office_list_source']}",
        f"- PEA office-count reference: {PEA_SERVICE_URL}",
        "- Scope: กฟจ. + กฟส. + กฟย. in Northeastern Thailand; regional offices are excluded.",
        f"- Target count from PEA service page: {sum(EXPECTED_COUNTS.values())}",
        f"- Output rows: {len(rows)}",
        "",
        "## Office count by type",
        "",
        "| Office group | Count | Expected |",
        "|---|---:|---:|",
    ]
    branch_like = counts_type.get("branch", 0) + counts_type.get("sub_branch", 0)
    expected_branch_like = EXPECTED_COUNTS["branch"] + EXPECTED_COUNTS["sub_branch"]
    lines.append(f"| provincial / กฟจ. | {counts_type.get('provincial', 0)} | {EXPECTED_COUNTS['provincial']} |")
    lines.append(f"| branch_or_subbranch / กฟส.+กฟย. | {branch_like} | {expected_branch_like} |")
    lines.append(f"| total | {len(rows)} | {sum(EXPECTED_COUNTS.values())} |")
    lines.extend(
        [
            "",
            "Note: `office_type` is inferred from public office names. The public office-search page often names both branch and sub-branch offices with district-level wording, so the `branch` vs `sub_branch` split is not authoritative. Use the combined `branch_or_subbranch` count for coverage.",
            "",
            "## Inferred office_type in output",
            "",
            "| Inferred office_type | Count |",
            "|---|---:|",
        ]
    )
    for office_type, count in counts_type.items():
        lines.append(f"| {office_type} | {count} |")
    lines.extend(["", "## Coordinate source", "", "| Source | Count |", "|---|---:|"])
    for source, count in counts_source.items():
        lines.append(f"| {source or 'missing'} | {count} |")
    lines.extend(["", "## Confidence", "", "| Confidence | Count |", "|---|---:|"])
    for conf, count in counts_conf.items():
        lines.append(f"| {conf} | {count} |")
    lines.extend(
        [
            "",
            "## QA notes",
            "",
            f"- Missing coordinate rows: {len(missing_coords)}",
            f"- Non-high confidence rows: {len(review_rows)}",
            "- `high` means the office name matched a Longdo PEA POI and coordinates were fetched from that POI page.",
            "- `medium` means a Longdo PEA POI matched but the score was weaker; inspect before production routing.",
            "- `low` means coordinate fallback came from Nominatim search; inspect before production routing.",
            "- `review` means no usable coordinate was fetched.",
            "",
            "## Outputs",
            "",
            f"- CSV: `{metadata['output_csv']}`",
            f"- SQLite: `{metadata['sqlite']}`",
        ]
    )
    if review_rows:
        lines.extend(["", "## Rows to review first", "", "| office_id | office_name | source | confidence |", "|---|---|---|---|"])
        for row in review_rows[:30]:
            lines.append(
                f"| {row['office_id']} | {row['office_name']} | {row['coordinate_source'] or 'missing'} | {row['confidence']} |"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.refresh_longdo_listing:
        refresh_longdo_listing_cache(
            Path(args.longdo_listing_cache),
            start_page=args.longdo_start_page,
            end_page=args.longdo_end_page,
            sleep_seconds=args.sleep_seconds,
        )

    if args.office_list_source == "info_center":
        html = load_info_center_html(Path(args.info_center_cache), args.refresh_info_center)
        offices = parse_info_center_offices(html)
        list_source_url = PEA_INFO_CENTER_URL
    else:
        html = load_office_search_html(Path(args.office_search_cache), args.refresh_office_search)
        offices = parse_official_ne_offices(html)
        list_source_url = PEA_OFFICE_SEARCH_URL
    pois = iter_cached_longdo_pois(Path(args.longdo_listing_cache))
    rows = build_rows(
        offices,
        pois,
        longdo_coord_cache_path=Path(args.longdo_coord_cache),
        nominatim_cache_path=Path(args.nominatim_cache),
        seed_coordinates_path=Path(args.seed_coordinates),
        sleep_seconds=args.sleep_seconds,
    )
    output = Path(args.output)
    sqlite_path = Path(args.sqlite)
    summary_path = Path(args.summary)
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_csv": str(output),
        "sqlite": str(sqlite_path),
        "summary": str(summary_path),
        "office_list_source": list_source_url,
        "office_count_reference": PEA_SERVICE_URL,
        "longdo_listing_cache": str(args.longdo_listing_cache),
        "rows": len(rows),
        "counts_by_type": counts_by(rows, "office_type"),
        "counts_by_confidence": counts_by(rows, "confidence"),
        "counts_by_source": counts_by(rows, "coordinate_source"),
    }
    write_csv(output, rows)
    write_sqlite(sqlite_path, rows, metadata)
    write_summary(summary_path, rows, metadata)
    return metadata


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build Northeastern Thailand PEA office coordinate table for กฟจ./กฟส./กฟย."
    )
    parser.add_argument("--info-center-cache", default=str(DEFAULT_INFO_CENTER_CACHE))
    parser.add_argument("--office-search-cache", default=str(DEFAULT_OFFICE_SEARCH_CACHE))
    parser.add_argument("--longdo-listing-cache", default=str(DEFAULT_LONGDO_LIST_CACHE))
    parser.add_argument("--longdo-coord-cache", default=str(DEFAULT_LONGDO_COORD_CACHE))
    parser.add_argument("--nominatim-cache", default=str(DEFAULT_NOMINATIM_CACHE))
    parser.add_argument("--seed-coordinates", default=str(DEFAULT_SEED_COORDINATES))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--sqlite", default=str(DEFAULT_SQLITE))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--refresh-info-center", action="store_true")
    parser.add_argument("--refresh-office-search", action="store_true")
    parser.add_argument("--office-list-source", choices=["office_search", "info_center"], default="office_search")
    parser.add_argument("--refresh-longdo-listing", action="store_true")
    parser.add_argument("--longdo-start-page", type=int, default=2200)
    parser.add_argument("--longdo-end-page", type=int, default=2400)
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
