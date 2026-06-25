import urllib.request
import urllib.parse
import json

def search_recloser_by_facilityid(keyword):
    encoded = urllib.parse.quote(keyword)
    url = (
        "https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/14/query"
        f"?where=FACILITYID+LIKE+%27%25{encoded}%25%27"
        "&outFields=FACILITYID,OPERATIONTYPE,LOCATION,FEEDERID,PHASEDESIGNATION,NUMBEROFUSER"
        "&returnGeometry=false"
        "&f=pjson"
    )
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode())

# ค้นหา Recloser พังโคน
data = search_recloser_by_facilityid("PFA")
features = data.get("features", [])
print(f"พบ Recloser ทั้งหมด {len(features)} อัน\n")

for i, f in enumerate(features, 1):
    attr = f.get("attributes", {})
    print(f"[{i}] FACILITYID : {attr.get('FACILITYID')}")
    print(f"    TYPE       : {attr.get('OPERATIONTYPE')}")
    print(f"    LOCATION   : {attr.get('LOCATION')}")
    print(f"    FEEDERID   : {attr.get('FEEDERID')}")
    print(f"    USERS      : {attr.get('NUMBEROFUSER')}")
    print()