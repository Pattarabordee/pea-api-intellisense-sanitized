import urllib.request
import urllib.parse
import json
import pandas as pd

def search_by_customername(name):
    encoded = urllib.parse.quote(name)
    url = (
        "https://gisne1.pea.co.th/arcgis/rest/services/PEA_QUERY/MapServer/29/query"
        f"?where=CUSTOMERNAME+LIKE+%27%25{encoded}%25%27"
        "&outFields=OBJECTID,FACILITYID,FEEDERID"
        "&returnGeometry=false"
        "&f=pjson"
    )
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())

# ===== ค้นหา =====
data = search_by_customername("SYNTHETIC_CUSTOMER_NAME")
features = data.get("features", [])
print(f"พบ {len(features)} รายการ")

if features:
    # แปลงเป็น DataFrame
    rows = [f.get("attributes", {}) for f in features]
    df = pd.DataFrame(rows)

    # Export
    df.to_excel("meter_customer_lookup.xlsx", index=False)
    df.to_csv("meter_customer_lookup.csv", index=False, encoding="utf-8-sig")

    print("Export เสร็จ:")
    print("  meter_customer_lookup.xlsx")
    print("  meter_customer_lookup.csv")
else:
    print("ไม่พบข้อมูล")
    print("Error:", data.get("error"))
