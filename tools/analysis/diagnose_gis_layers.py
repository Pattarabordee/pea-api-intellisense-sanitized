"""
diagnose_gis_layers.py
======================
รันบนเครื่อง PEA แล้วส่งผล (console output) กลับมาให้ดู
เพื่อหาว่า GIS tag ใน Event file ตรงกับ field ไหนใน API จริงๆ
"""
import urllib.request, urllib.parse, json, time

BASE_URL = "https://gisne1.pea.co.th/arcgis/rest/services"
# BASE_URL = "http://172.16.184.233/arcgis/rest/services"  # ← ลอง Intranet ด้วย

def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PEA-Diag/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return {"_error": str(e)}

def sep(title=""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
        print('='*60)

# ── 1) Schema ของแต่ละ Layer ────────────────────────────────────
for layer_id, name in [(17,"DS_Transformer"), (16,"DS_Switch"),
                        (14,"DS_Recloser"),   (11,"DS_CircuitBreaker")]:
    sep(f"Layer {layer_id} — {name} — FIELDS")
    data = fetch(f"{BASE_URL}/PEA/MapServer/{layer_id}?f=pjson")
    if "_error" in data:
        print(f"  ERROR: {data['_error']}")
        continue
    for f in data.get("fields", []):
        print(f"  {f['name']:35s} {f['type']}")
    time.sleep(0.4)

# ── 2) Sample 3 records จาก Layer 17 — ดูค่าจริงใน field ─────
sep("Layer 17 — 3 sample records (no filter)")
params = urllib.parse.urlencode({
    "where": "1=1", "outFields": "*",
    "returnGeometry": "false", "resultRecordCount": 3, "f": "pjson"
})
data = fetch(f"{BASE_URL}/PEA/MapServer/17/query?{params}")
if "_error" in data:
    print(f"  ERROR: {data['_error']}")
else:
    for feat in data.get("features", []):
        print(feat.get("attributes", {}))
time.sleep(0.4)

# ── 3) หา GIS tag จริงๆ ว่าอยู่ใน field ไหน ──────────────────
TEST_TAGS = [
    "2147XF000000105",      # XF pattern
    "21SWDA000124552",      # SW pattern
    "2147SW000000083",      # SW pattern 2
]
FIELDS_TO_TRY = [
    "FACILITYID", "GLOBALID", "GIS_TAG", "OBJECTID_STR",
    "TAG", "FEEDERID", "PEANO", "INSTALLATIONID",
]

sep("ค้นหา GIS tag ใน field ต่างๆ — Layer 17, 16, 14")
for tag in TEST_TAGS:
    print(f"\n  tag = {tag}")
    for layer_id in [17, 16, 14]:
        for field in FIELDS_TO_TRY:
            params = urllib.parse.urlencode({
                "where": f"{field}='{tag}'",
                "outFields": "*", "returnGeometry": "false", "f": "pjson"
            })
            data = fetch(f"{BASE_URL}/PEA/MapServer/{layer_id}/query?{params}")
            if "_error" in data:
                continue  # field ไม่มีใน layer นี้
            feats = data.get("features", [])
            if feats:
                print(f"    ✅ FOUND  layer={layer_id}  field={field}")
                print(f"       {feats[0].get('attributes',{})}")
            time.sleep(0.2)

# ── 4) ลอง LIKE query แบบกว้างๆ ─────────────────────────────
sep("LIKE query Layer 17 เพื่อหา tag pattern")
for pattern in ["%XF000000105%", "%000000105%", "%2147XF%"]:
    params = urllib.parse.urlencode({
        "where": f"FACILITYID LIKE '{pattern}'",
        "outFields": "FACILITYID,FEEDERID",
        "returnGeometry": "false", "resultRecordCount": 3, "f": "pjson"
    })
    data = fetch(f"{BASE_URL}/PEA/MapServer/17/query?{params}")
    feats = data.get("features", [])
    err   = data.get("error", {})
    print(f"  LIKE '{pattern}': {len(feats)} results  {err if err else ''}")
    for feat in feats:
        print(f"    {feat.get('attributes',{})}")
    time.sleep(0.3)

# ── 5) ดู Layer 26 — sample + ลอง PEANO format ──────────────
sep("Layer 26 — 3 sample records")
params = urllib.parse.urlencode({
    "where": "1=1", "outFields": "PEANO,FEEDERID,INSTALLATIONID,ACCOUNTNUMBER",
    "returnGeometry": "false", "resultRecordCount": 3, "f": "pjson"
})
data = fetch(f"{BASE_URL}/PEA/MapServer/26/query?{params}")
if "_error" in data:
    print(f"  ERROR: {data['_error']}")
else:
    for feat in data.get("features", []):
        print(feat.get("attributes", {}))
time.sleep(0.4)

# ── 6) ลอง INSTALLATIONID แทน PEANO สำหรับ tag แบบ 10-digit suffix
sep("ลอง INSTALLATIONID ด้วย tag 10-digit-suffix")
test_numeric = "6000556881"   # ตัดจาก 6000556881-1060050001
for field in ["PEANO", "INSTALLATIONID", "ACCOUNTNUMBER"]:
    params = urllib.parse.urlencode({
        "where": f"{field}='{test_numeric}'",
        "outFields": "*", "returnGeometry": "false", "f": "pjson"
    })
    for svc_layer in [("PEA", 26), ("PEA_QUERY", 29)]:
        data = fetch(f"{BASE_URL}/{svc_layer[0]}/MapServer/{svc_layer[1]}/query?{params}")
        if "_error" in data:
            continue
        feats = data.get("features", [])
        if feats:
            print(f"  ✅ FOUND  svc={svc_layer[0]}  layer={svc_layer[1]}  field={field}")
            print(f"     {feats[0].get('attributes',{})}")
        else:
            print(f"  svc={svc_layer[0]}  layer={svc_layer[1]}  field={field}: 0")
        time.sleep(0.2)

print("\n\nDone. ส่ง output ทั้งหมดนี้กลับมาครับ")
