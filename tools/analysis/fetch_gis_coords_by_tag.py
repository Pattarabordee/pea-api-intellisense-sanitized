import urllib.request
import urllib.parse
import json
import pandas as pd
import time
from pyproj import Transformer

# แปลงพิกัด EPSG:3857 -> WGS84
transformer = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

# Layer ที่จะค้นตามลำดับ
LAYERS = {
    "17": "Transformer (XF)",
    "14": "Recloser (RC)",
    "16": "Switch (SW)",
    "13": "PrimaryMeter",
    "26": "LVMeter",
}

def fetch_url(url, timeout=30, retries=3):
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            print(f"  Retry {attempt+1}/{retries}: {e}")
            time.sleep(2)
    return None

def get_coords_by_tag(tag, layer_id):
    """ค้นหาพิกัดจาก TAG field"""
    encoded = urllib.parse.quote(f"TAG='{tag}'")
    url = (
        f"https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/{layer_id}/query"
        f"?where={encoded}"
        "&outFields=TAG,FACILITYID,FEEDERID"
        "&returnGeometry=true"
        "&f=pjson"
    )
    data = fetch_url(url)
    if not data:
        return None
    features = data.get("features", [])
    if not features:
        return None
    geom = features[0].get("geometry", {})
    attr = features[0].get("attributes", {})
    x = geom.get("x")
    y = geom.get("y")
    if x is None or y is None:
        return None
    lon, lat = transformer.transform(x, y)
    return {
        "lon"        : lon,
        "lat"        : lat,
        "FACILITYID" : attr.get("FACILITYID"),
        "FEEDERID"   : attr.get("FEEDERID"),
        "found_layer": layer_id,
    }

def get_coords_batch(tags):
    """ค้นหาพิกัดของหลาย tag พร้อมกัน (batch 50 tags)"""
    # สร้าง IN clause
    tag_list = "','".join(tags)
    encoded = urllib.parse.quote(f"TAG IN ('{tag_list}')")
    url = (
        f"https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/17/query"
        f"?where={encoded}"
        "&outFields=TAG,FACILITYID,FEEDERID"
        "&returnGeometry=true"
        "&f=pjson"
    )
    return fetch_url(url)

# ===== พิกัดสถานีต้นทาง =====
STATION_COORDS = {
    "PFA": {"station_lon": 103.9514, "station_lat": 17.2908},  # พังโคน
    "WWA": {"station_lon": 103.7411, "station_lat": 17.6371},  # วานรนิวาส
    "SEK": {"station_lon": 105.0378, "station_lat": 18.0678},  # เซกา
    "XIA": {"station_lon": 104.1234, "station_lat": 17.4567},  # เซียม (ประมาณ)
    "BDH": {"station_lon": 103.2567, "station_lat": 17.6789},  # บ้านดุง (ประมาณ)
}

def haversine(lon1, lat1, lon2, lat2):
    import numpy as np
    R = 6371
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi/2)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlam/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))

# ===== Main =====
# โหลด unique tags จากไฟล์ Event
df_event = pd.read_excel("Event_from_report52_PKN.xlsx")
unique_tags = df_event["OpDeviceGIStag"].dropna().unique()
print(f"unique tags ทั้งหมด: {len(unique_tags)}")

results = []
not_found = []

for i, tag in enumerate(unique_tags, 1):
    tag = str(tag).strip()
    found = None

    # ค้นทีละ Layer จนเจอ
    for layer_id in LAYERS.keys():
        found = get_coords_by_tag(tag, layer_id)
        if found:
            found["OpDeviceGIStag"] = tag
            break

    if found:
        # คำนวณ distance_km
        prefix = str(df_event[df_event["OpDeviceGIStag"] == tag]["Feeder"].iloc[0])[:3]
        station = STATION_COORDS.get(prefix, {})
        if station:
            found["distance_km"] = haversine(
                found["lon"], found["lat"],
                station["station_lon"], station["station_lat"]
            )
            found["station_prefix"] = prefix
        results.append(found)
        print(f"[{i}/{len(unique_tags)}] {tag} -> Layer {found['found_layer']} | {found['lat']:.4f}, {found['lon']:.4f}")
    else:
        not_found.append(tag)
        print(f"[{i}/{len(unique_tags)}] {tag} -> ไม่พบ")

    # Checkpoint ทุก 100 tags
    if i % 100 == 0:
        pd.DataFrame(results).to_csv(f"checkpoint_{i}.csv", index=False, encoding="utf-8-sig")
        print(f"  Checkpoint saved: checkpoint_{i}.csv")

    time.sleep(0.3)  # หน่วงเล็กน้อย

# ===== Export =====
df_result = pd.DataFrame(results)
df_result.to_csv("gis_coords_by_tag.csv", index=False, encoding="utf-8-sig")
df_result.to_excel("gis_coords_by_tag.xlsx", index=False)

print(f"\nเสร็จสิ้น")
print(f"  พบพิกัด : {len(results)} tags")
print(f"  ไม่พบ   : {len(not_found)} tags")
print(f"  Export  : gis_coords_by_tag.csv / gis_coords_by_tag.xlsx")

if not_found:
    pd.DataFrame({"OpDeviceGIStag": not_found}).to_csv("not_found_tags.csv", index=False)
    print(f"  ไม่พบ   : not_found_tags.csv")