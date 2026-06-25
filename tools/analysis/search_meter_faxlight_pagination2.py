import urllib.request
import urllib.parse
import json
import pandas as pd

def fetch_page(name, offset, page_size=1000):
    encoded = urllib.parse.quote(name)
    url = (
        "https://gisne1.pea.co.th/arcgis/rest/services/PEA_QUERY/MapServer/29/query"
        f"?where=CUSTOMERNAME+LIKE+%27%25{encoded}%25%27"
        "&outFields=OBJECTID,FACILITYID,FEEDERID"
        "&returnGeometry=false"
        f"&resultOffset={offset}"
        f"&resultRecordCount={page_size}"
        "&orderByFields=OBJECTID"
        "&f=pjson"
    )
    print(f"  URL: {url}")  # debug ดู URL จริง
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read().decode())
    
    # แสดง error ถ้ามี
    if data.get("error"):
        print(f"  API Error: {data.get('error')}")
    
    return data

# ===== Pagination =====
CUSTOMER = "SYNTHETIC_CUSTOMER_NAME"
PAGE_SIZE = 1000
all_rows = []
offset = 0

while True:
    print(f"ดึงข้อมูล offset {offset}...")
    data = fetch_page(CUSTOMER, offset, PAGE_SIZE)
    features = data.get("features", [])

    if not features:
        print(f"  ได้ 0 features หยุด")
        break

    for f in features:
        all_rows.append(f.get("attributes", {}))

    print(f"  ได้ {len(features)} records | รวมสะสม {len(all_rows)}")

    if len(features) < PAGE_SIZE:
        break

    offset += PAGE_SIZE

# ===== Export =====
print(f"\nรวมทั้งหมด {len(all_rows)} รายการ")
if all_rows:
    df = pd.DataFrame(all_rows)
    df.to_excel("meter_customer_lookup.xlsx", index=False)
    df.to_csv("meter_customer_lookup.csv", index=False, encoding="utf-8-sig")
    print("Export เสร็จ: meter_customer_lookup.xlsx / meter_customer_lookup.csv")
