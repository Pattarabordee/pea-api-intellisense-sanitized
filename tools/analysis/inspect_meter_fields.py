import urllib.request
import json

# ดู field ของ Layer 13 และ 26
for layer_id in ["13", "26"]:
    url = (
        f"https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/{layer_id}/query"
        "?where=1%3D1&outFields=*&resultRecordCount=1&f=pjson"
    )
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read().decode())
    
    print(f"\n{'='*50}")
    print(f"Layer {layer_id}")
    print(f"{'='*50}")
    if data.get("features"):
        print(json.dumps(data["features"][0]["attributes"], indent=2, ensure_ascii=False))
    else:
        print("ไม่มีข้อมูล")