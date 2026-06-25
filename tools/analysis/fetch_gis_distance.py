"""
fetch_gis_distance.py  (v3 — แก้ routing ครบทุก pattern)
==========================================================
ดึงพิกัด (lat, lon) ของ OpDeviceGIStag ทุกตัวจาก PEA GIS API
แล้วคำนวณระยะทาง (km) จากสถานีต้นสังกัดถึงอุปกรณ์ที่เกิดเหตุ

Output: gis_distance.csv
  OpDeviceGIStag | lon | lat | station_code | station_lon | station_lat
                 | distance_km | layer | facilityid | status

root cause ของ NOT_FOUND ที่แก้ใน v3:
  A) 2147RC... → Layer 14  field TAG           (ลืม route)
  B) 21xxxxxx-1060... → Layer 26  field PEANO  (ส่งไป Layer 14 ผิด)
  C) 8-digit PEANO → Layer 26  field PEANO     (ยังหาได้)
  D) alpha-prefix C/B/D... → Layer 26  field ACCOUNTNUMBER
  E) XF/SW NOT_FOUND 73 → ลอง TAG แบบ LIKE fallback
"""

import urllib.request
import urllib.parse
import json
import time
import re
import math
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL    = "https://gisne1.pea.co.th/arcgis/rest/services"
# BASE_URL  = "http://172.16.184.233/arcgis/rest/services"  # ← Intranet PEA
EVENT_FILE  = "Event_from_report52_PKN.xlsx"
OUTPUT_FILE = "gis_distance.csv"
SLEEP_SEC   = 0.35
BATCH_SIZE  = 50

# ── พิกัดสถานีต้นทาง (WGS84) ─────────────────────────────────────────────────
STATION_COORDS = {
    "PFA": (103.9525, 17.5831),
    "WWA": (103.7300, 17.6360),
    "WDA": (103.8570, 17.4240),
    "SEK": (104.1500, 17.6500),
    "XIA": (103.6500, 17.3000),
    "BDH": (103.2500, 17.6900),
    "SOA": (104.1500, 17.1550),
    "NPA": (104.7500, 17.4100),
    "DPF": (103.9500, 17.0000),
}


# ── TAG classifier — ส่งคืน list[(layer, field, query_value)] ────────────────
def classify_tag(tag: str) -> list:
    """
    จำแนก GIS tag → list ของ (layer_id, field, value_to_query)
    ลองตามลำดับ ถ้าพบแล้วหยุด

    Pattern ที่พบใน Event file:
      2147XF...        → Layer 17  TAG
      21xxXF...        → Layer 17  TAG
      21SWDA.../21xxSW → Layer 16  TAG
      2147SW...        → Layer 16  TAG
      2147RC...        → Layer 14  TAG     ← v3 เพิ่ม
      21xxxxxx-1060... → Layer 26  PEANO   ← v3 แก้ (เดิมส่งไป 14)
      10-digit-suffix  → Layer 26  PEANO
      8-digit-suffix   → Layer 26  PEANO   ← v3 เพิ่ม
      7-digit-suffix   → Layer 26  PEANO   ← v3 เพิ่ม
      alpha-prefix     → Layer 26  ACCOUNTNUMBER ← v3 เพิ่ม
    """
    t   = str(tag)
    # ตัด suffix เช่น -1060050001-D-5964146 ออก เอาแค่ส่วนแรก
    base = t.split("-")[0] if "-" in t else t

    # อุปกรณ์ MV — ระบุด้วย prefix 21xxXF / 21xxSW / 21xxRC
    if re.match(r'^21\d{2}XF',  t): return [(17, "TAG", t)]
    if re.match(r'^21SW',        t): return [(16, "TAG", t)]
    if re.match(r'^21\d{2}SW',  t): return [(16, "TAG", t)]
    if re.match(r'^21\d{2}RC',  t): return [(14, "TAG", t)]   # Recloser

    # 21xxxxxx (ตัวเลข 8 หลัก ขึ้นต้น 21) → Meter ใน Layer 26
    if re.match(r'^21\d{6}$', base): return [(26, "PEANO", base)]

    # alpha-prefix A/B/C/D → ACCOUNTNUMBER ใน Layer 26
    if re.match(r'^[A-Za-z]\d', base): return [(26, "ACCOUNTNUMBER", base)]

    # numeric (8, 10 digit) → PEANO ใน Layer 26
    if re.match(r'^\d+$', base): return [(26, "PEANO", base)]

    # fallback — ลองทุก layer
    return [(17, "TAG", t), (16, "TAG", t), (14, "TAG", t)]


# ── HTTP helper ───────────────────────────────────────────────────────────────
def fetch(url: str, timeout: int = 45, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PEA-ML/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"    [WARN] {e}")
    return {}


def query_mv_layer(layer_id: int, field: str, values: list) -> list:
    """Query Layer 14/16/17 ด้วย field IN (...) → features พร้อม geometry WGS84"""
    val_list = ",".join(f"'{v}'" for v in values)
    params = urllib.parse.urlencode({
        "where":          f"{field} IN ({val_list})",
        "outFields":      f"{field},FACILITYID,FEEDERID,LOCATION",
        "returnGeometry": "true",
        "outSR":          "4326",
        "f":              "pjson",
    })
    data = fetch(f"{BASE_URL}/PEA/MapServer/{layer_id}/query?{params}")
    time.sleep(SLEEP_SEC)
    return data.get("features", [])


def query_lv_layer(field: str, values: list) -> list:
    """Query Layer 26 ด้วย PEANO/ACCOUNTNUMBER IN (...) → features พร้อม geometry WGS84"""
    val_list = ",".join(f"'{v}'" for v in values)
    params = urllib.parse.urlencode({
        "where":          f"{field} IN ({val_list})",
        "outFields":      f"TAG,PEANO,ACCOUNTNUMBER,FEEDERID,INSTALLATIONID",
        "returnGeometry": "true",
        "outSR":          "4326",
        "f":              "pjson",
    })
    data = fetch(f"{BASE_URL}/PEA/MapServer/26/query?{params}")
    time.sleep(SLEEP_SEC)
    return data.get("features", [])


def haversine(lon1, lat1, lon2, lat2) -> float:
    R    = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a    = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def feeder_to_station(feeder: str) -> str:
    return re.sub(r'\d.*$', '', str(feeder)).upper()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    # 1) โหลด Event file
    print("Loading Event file...")
    df_event = pd.read_excel(EVENT_FILE, header=2)
    tag_meta = (
        df_event[["OpDeviceGIStag", "Feeder", "OpDeviceType"]]
        .dropna(subset=["OpDeviceGIStag"])
        .drop_duplicates("OpDeviceGIStag")
        .copy()
    )
    tag_meta["OpDeviceGIStag"] = tag_meta["OpDeviceGIStag"].astype(str)
    tag_meta["station_code"]   = tag_meta["Feeder"].apply(feeder_to_station)
    tag_meta["candidates"]     = tag_meta["OpDeviceGIStag"].apply(classify_tag)
    print(f"  Unique tags: {len(tag_meta):,}")

    # 2) จัดกลุ่มการ query
    # แต่ละ tag มี candidates = [(layer, field, value), ...]
    # รวม batch ตาม (layer, field) เดียวกัน

    # สร้าง work items — ลอง candidate แรกก่อน
    # key = (layer, field), value = {query_value: original_tag}
    from collections import defaultdict
    work = defaultdict(dict)   # (layer, field) → {qval: orig_tag}

    for _, row in tag_meta.iterrows():
        orig  = row["OpDeviceGIStag"]
        cands = row["candidates"]
        lyr, fld, qval = cands[0]
        work[(lyr, fld)][qval] = orig

    # แสดง distribution
    print("\n  Query plan:")
    for (lyr, fld), mapping in sorted(work.items()):
        print(f"    Layer {lyr:2d}  field={fld:15s}  {len(mapping):4d} tags")

    # 3) Execute queries
    found_map = {}  # orig_tag → {"lon","lat","layer","facilityid"}

    for (layer_id, field), qval_to_orig in sorted(work.items()):
        qvals = list(qval_to_orig.keys())
        layer_names = {14:"Recloser", 16:"Switch/DOF", 17:"Transformer", 26:"LV Meter"}
        print(f"\nQuerying Layer {layer_id} — {layer_names.get(layer_id,'')} "
              f"field={field} ({len(qvals)} tags, batch={BATCH_SIZE})...")

        for i in range(0, len(qvals), BATCH_SIZE):
            batch = qvals[i : i + BATCH_SIZE]

            if layer_id == 26:
                feats = query_lv_layer(field, batch)
            else:
                feats = query_mv_layer(layer_id, field, batch)

            for feat in feats:
                attr = feat.get("attributes", {})
                geom = feat.get("geometry", {})
                if not geom or geom.get("x") is None:
                    continue

                # match กลับไปหา original tag
                matched_orig = None
                for key_field in [field, "TAG", "PEANO", "ACCOUNTNUMBER"]:
                    qv = str(attr.get(key_field, "") or "")
                    if qv in qval_to_orig:
                        matched_orig = qval_to_orig[qv]
                        break

                if matched_orig and matched_orig not in found_map:
                    found_map[matched_orig] = {
                        "lon":        geom["x"],
                        "lat":        geom["y"],
                        "layer":      layer_id,
                        "facilityid": attr.get("FACILITYID") or attr.get("TAG") or "",
                    }

            n = i // BATCH_SIZE + 1
            print(f"  batch {n:3d}: got {len(feats):3d} | total found: {len(found_map):,}")

    # 4) Fallback: tag ที่ยังไม่เจอ ลอง candidate ที่ 2 (ถ้ามี)
    not_found_yet = [
        row for _, row in tag_meta.iterrows()
        if row["OpDeviceGIStag"] not in found_map and len(row["candidates"]) > 1
    ]
    if not_found_yet:
        print(f"\n--- Fallback: {len(not_found_yet)} tags ลอง candidate ที่ 2 ---")
        fb_work = defaultdict(dict)
        for row in not_found_yet:
            orig = row["OpDeviceGIStag"]
            lyr, fld, qval = row["candidates"][1]
            fb_work[(lyr, fld)][qval] = orig

        for (layer_id, field), qval_to_orig in sorted(fb_work.items()):
            qvals = list(qval_to_orig.keys())
            print(f"  Fallback Layer {layer_id} field={field} ({len(qvals)} tags)...")
            for i in range(0, len(qvals), BATCH_SIZE):
                batch = qvals[i : i + BATCH_SIZE]
                feats = query_mv_layer(layer_id, field, batch) if layer_id != 26 \
                        else query_lv_layer(field, batch)
                for feat in feats:
                    attr = feat.get("attributes", {})
                    geom = feat.get("geometry", {})
                    if not geom or geom.get("x") is None:
                        continue
                    for key_field in [field, "TAG", "PEANO"]:
                        qv = str(attr.get(key_field, "") or "")
                        if qv in qval_to_orig:
                            orig = qval_to_orig[qv]
                            if orig not in found_map:
                                found_map[orig] = {
                                    "lon":        geom["x"],
                                    "lat":        geom["y"],
                                    "layer":      layer_id,
                                    "facilityid": attr.get("FACILITYID") or attr.get("TAG") or "",
                                }
                            break
            print(f"    total found now: {len(found_map):,}")

    # 5) รวมผล + คำนวณ distance
    print("\nComputing distances...")
    rows = []
    for _, r in tag_meta.iterrows():
        tag  = r["OpDeviceGIStag"]
        info = found_map.get(tag)
        sc   = r["station_code"]
        slon, slat = STATION_COORDS.get(sc, (None, None))
        if info:
            lon, lat = info["lon"], info["lat"]
            dist = round(haversine(lon, lat, slon, slat), 4) if slon else None
            rows.append({
                "OpDeviceGIStag": tag,
                "lon": lon, "lat": lat,
                "station_code": sc, "station_lon": slon, "station_lat": slat,
                "distance_km": dist,
                "layer": info["layer"], "facilityid": info["facilityid"],
                "status": "OK",
            })
        else:
            rows.append({
                "OpDeviceGIStag": tag,
                "lon": None, "lat": None,
                "station_code": sc, "station_lon": slon, "station_lat": slat,
                "distance_km": None,
                "layer": None, "facilityid": None,
                "status": "NOT_FOUND",
            })

    df_result = pd.DataFrame(rows)
    df_result.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    # 6) สรุป
    ok    = (df_result["status"] == "OK").sum()
    nf    = (df_result["status"] == "NOT_FOUND").sum()
    total = len(df_result)
    print(f"\n{'='*55}")
    print(f"เสร็จสิ้น — บันทึกที่ {OUTPUT_FILE}")
    print(f"  OK        : {ok:,} / {total:,} ({ok/total*100:.1f}%)")
    print(f"  NOT_FOUND : {nf:,} / {total:,} ({nf/total*100:.1f}%)")
    if ok > 0:
        print(f"\n  distance_km stats:")
        print(df_result[df_result["status"]=="OK"]["distance_km"].describe().round(3).to_string())
    print(f"\n  Layer breakdown (OK):")
    print(df_result[df_result["status"]=="OK"].groupby("layer").size().to_string())
    cols = ["OpDeviceGIStag","lon","lat","distance_km","layer","facilityid","status"]
    print(f"\n  ตัวอย่าง 5 แถวแรก:")
    print(df_result[cols].head().to_string(index=False))


if __name__ == "__main__":
    main()
