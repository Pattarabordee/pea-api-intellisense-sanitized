import urllib.request
import json

# ดู fields ของ Layer 17 (Transformer) และ Layer 14 (Recloser)
for layer_id in ["14", "17"]:
    url = (
        f"https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/{layer_id}/query"
        "?where=1%3D1&outFields=*&resultRecordCount=1&f=pjson"
    )
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.loads(r.read().decode())
    
    print(f"\n{'='*50}")
    print(f"Layer {layer_id}")
    print(f"{'='*50}")
    if data.get("features"):
        attrs = data["features"][0]["attributes"]
        for key, val in attrs.items():
            print(f"  {key}: {val}")