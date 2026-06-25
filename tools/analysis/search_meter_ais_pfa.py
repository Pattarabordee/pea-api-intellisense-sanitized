import urllib.request
import urllib.parse
import json

# keyword ที่ AIS ใช้จดทะเบียน
AIS_KEYWORDS = [
    "แอดวานซ์ อินโฟร์",
    "แอดวานซ์ ไวร์เลส",
    "แอดวานซ์ บรอดแบนด์",
    "ซุปเปอร์ บรอดแบนด์",
    "ADVANCE INFO",
    "ADVANCE WIRELESS",
    "AWN",
    "AIS",
]

# Layer ที่ต้องค้น
LAYERS = {
    "13": "DS_PrimaryMeter (มิเตอร์แรงกลาง)",
    "26": "DS_LowVoltageMeter (มิเตอร์แรงต่ำ)",
}

def search_meter_by_name(layer_id, keyword):
    encoded = urllib.parse.quote(keyword)
    url = (
        f"https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/{layer_id}/query"
        f"?where=FACILITYID+LIKE+%27%25PFA%25%27"  # กรองเฉพาะพังโคนก่อน
        f"+AND+OWNER+LIKE+%27%25{encoded}%25%27"
        "&outFields=FACILITYID,FEEDERID"
        "&returnGeometry=false"
        "&f=pjson"
    )
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())

# ===== Main =====
all_results = []

for layer_id, layer_name in LAYERS.items():
    print(f"\n{'='*50}")
    print(f"Layer {layer_id}: {layer_name}")
    print(f"{'='*50}")
    
    for kw in AIS_KEYWORDS:
        try:
            data = search_meter_by_name(layer_id, kw)
            features = data.get("features", [])
            if features:
                print(f"\n  keyword '{kw}' -> พบ {len(features)} รายการ")
                for f in features:
                    attr = f.get("attributes", {})
                    print(f"    FACILITYID : {attr.get('FACILITYID')}")
                    print(f"    FEEDERID   : {attr.get('FEEDERID')}")
                    print()
                    all_results.append(attr)
        except Exception as e:
            print(f"  Error '{kw}': {e}")

print(f"\nรวมพบทั้งหมด {len(all_results)} มิเตอร์")
