import urllib.request
import urllib.parse
import json

def search_recloser(location_keyword):
    # แปลง keyword เป็น URL Encode ก่อน
    encoded_keyword = urllib.parse.quote(location_keyword)
    
    url = (
        "https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/14/query"
        f"?where=LOCATION+LIKE+%27%25{encoded_keyword}%25%27"
        "&outFields=FACILITYID,OPERATIONTYPE,LOCATION,FEEDERID,FEEDERID2,PHASEDESIGNATION,OWNER,NUMBEROFUSER"
        "&returnGeometry=false"
        "&f=pjson"
    )
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())

# ===== ค้นหาพังโคน =====
keywords = ["พังโคน"]

for kw in keywords:
    try:
        data = search_recloser(kw)
        features = data.get("features", [])
        print(f"\nค้นด้วย '{kw}' -> พบ {len(features)} รายการ")
        for i, f in enumerate(features, 1):
            attr = f.get("attributes", {})
            print(f"\n  [{i}] FACILITYID      : {attr.get('FACILITYID')}")
            print(f"      OPERATIONTYPE   : {attr.get('OPERATIONTYPE')}")
            print(f"      LOCATION        : {attr.get('LOCATION')}")
            print(f"      FEEDERID        : {attr.get('FEEDERID')}")
            print(f"      PHASEDESIGNATION: {attr.get('PHASEDESIGNATION')}")
            print(f"      NUMBEROFUSER    : {attr.get('NUMBEROFUSER')}")
            print(f"      OWNER           : {attr.get('OWNER')}")
    except Exception as e:
        print(f"Error: {e}")