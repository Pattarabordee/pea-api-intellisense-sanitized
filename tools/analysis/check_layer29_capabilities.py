import urllib.request
import json

# ดู capabilities ของ Layer 29
url = (
    "https://gisne1.pea.co.th/arcgis/rest/services/PEA_QUERY/MapServer/29"
    "?f=pjson"
)
with urllib.request.urlopen(url, timeout=30) as r:
    data = json.loads(r.read().decode())

print("advancedQueryCapabilities:")
aq = data.get("advancedQueryCapabilities", {})
for key, val in aq.items():
    print(f"  {key}: {val}")

print("\nmaxRecordCount:", data.get("maxRecordCount"))
print("supportsPagination:", aq.get("supportsPagination"))
print("supportsOrderBy:", aq.get("supportsOrderBy"))