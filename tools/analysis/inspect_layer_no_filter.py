import urllib.request
import json

# ===== Layer 26 ไม่กรองอะไรเลย =====
print("=" * 50)
print("Layer 26: DS_LowVoltageMeter")
print("=" * 50)
url26 = (
    "https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/26/query"
    "?where=1%3D1"
    "&outFields=*"
    "&resultRecordCount=1"
    "&f=pjson"
)
with urllib.request.urlopen(url26, timeout=60) as r:
    data26 = json.loads(r.read().decode())

features = data26.get("features", [])
if features:
    print(json.dumps(features[0]["attributes"], indent=2, ensure_ascii=False))
else:
    print("ไม่พบข้อมูล — Layer 26 อาจว่างเปล่าหรือต้องการสิทธิ์พิเศษ")
    print("Error:", data26.get("error"))

# ===== Layer 13 ไม่กรองอะไรเลย =====
print("\n" + "=" * 50)
print("Layer 13: DS_PrimaryMeter")
print("=" * 50)
url13 = (
    "https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/13/query"
    "?where=1%3D1"
    "&outFields=OWNER"
    "&returnGeometry=false"
    "&returnDistinctValues=true"
    "&orderByFields=OWNER"
    "&f=pjson"
)
with urllib.request.urlopen(url13, timeout=60) as r:
    data13 = json.loads(r.read().decode())

features13 = data13.get("features", [])
if features13:
    print(f"OWNER ทั้งหมดในระบบ ({len(features13)} ค่า):")
    for f in features13:
        print(f"  {f['attributes'].get('OWNER')}")
else:
    print("ไม่พบข้อมูล")
    print("Error:", data13.get("error"))