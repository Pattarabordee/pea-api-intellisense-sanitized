import urllib.request
import json

# ดู 1 record เพื่อเช็ค field และรูปแบบข้อมูล
url = "https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/14/query?where=1%3D1&outFields=*&resultRecordCount=1&f=pjson"
with urllib.request.urlopen(url) as r:
    data = json.loads(r.read().decode())
print(json.dumps(data["features"][0], indent=2, ensure_ascii=False))