import urllib.request
import urllib.parse
import json

def search_recloser(location_keyword):
    encoded_keyword = urllib.parse.quote(location_keyword)
    url = (
        "https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/14/query"
        f"?where=LOCATION+LIKE+%27%25{encoded_keyword}%25%27"
        "&outFields=FACILITYID,OPERATIONTYPE,LOCATION,FEEDERID"
        "&returnGeometry=false"
        "&f=pjson"
    )
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())

# ลองหลายคำ
keywords = ["พังโคน", "พัง", "โคน", "PHANG", "PKN", "สกลนคร"]

for kw in keywords:
    try:
        data = search_recloser(kw)
        features = data.get("features", [])
        print(f"'{kw}' -> {len(features)} รายการ")
        for f in features[:3]:  # แสดงแค่ 3 รายการแรก
            attr = f.get("attributes", {})
            print(f"   {attr.get('FACILITYID')} | {attr.get('LOCATION')}")
    except Exception as e:
        print(f"Error '{kw}': {e}")