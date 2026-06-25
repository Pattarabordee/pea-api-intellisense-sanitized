import urllib.request
import json

url = (
    "https://gisne1.pea.co.th/arcgis/rest/services/PEA_QUERY/MapServer/29/query"
    "?where=1%3D1&outFields=*&resultRecordCount=1&f=pjson"
)
with urllib.request.urlopen(url, timeout=30) as r:
    data = json.loads(r.read().decode())

features = data.get("features", [])
if features:
    print(json.dumps(features[0]["attributes"], indent=2, ensure_ascii=False))
else:
    print("ไม่พบข้อมูล")
    print("Error:", data.get("error"))