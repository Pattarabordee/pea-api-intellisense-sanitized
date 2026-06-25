import urllib.request
import json

# ===== Layer 26 fields (กรอง PFA เพื่อให้เร็วขึ้น) =====
print("=" * 50)
print("Layer 26: DS_LowVoltageMeter")
print("=" * 50)
url26 = (
    "https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/26/query"
    "?where=FACILITYID+LIKE+%27%25PFA%25%27"
    "&outFields=*"
    "&resultRecordCount=1"
    "&f=pjson"
)
with urllib.request.urlopen(url26, timeout=30) as r:
    data26 = json.loads(r.read().decode())

features = data26.get("features", [])
if features:
    print(json.dumps(features[0]["attributes"], indent=2, ensure_ascii=False))
else:
    print("ไม่พบข้อมูล")

# ===== ค่า OWNER ที่มีทั้งหมดใน Layer 13 =====
print("\n" + "=" * 50)
print("OWNER values ใน Layer 13 (PFA)")
print("=" * 50)
url_owner = (
    "https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/13/query"
    "?where=FACILITYID+LIKE+%27%25PFA%25%27"
    "&outFields=OWNER"
    "&returnGeometry=false"
    "&returnDistinctValues=true"
    "&orderByFields=OWNER"
    "&f=pjson"
)
with urllib.request.urlopen(url_owner, timeout=30) as r:
    data_owner = json.loads(r.read().decode())

for f in data_owner.get("features", []):
    print(f"  {f['attributes'].get('OWNER')}")