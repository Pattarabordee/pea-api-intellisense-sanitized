import urllib.request
import urllib.parse
import json

def count_records(name):
    encoded = urllib.parse.quote(name)
    url = (
        "https://gisne1.pea.co.th/arcgis/rest/services/PEA_QUERY/MapServer/29/query"
        f"?where=CUSTOMERNAME+LIKE+%27%25{encoded}%25%27"
        "&returnCountOnly=true"
        "&f=pjson"
    )
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode())

data = count_records("แฟกซ์ ไลท์")
print(f"จำนวนจริง: {data.get('count')} รายการ")