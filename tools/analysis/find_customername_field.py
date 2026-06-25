import urllib.request
import urllib.parse
import json

# ลองทุก Layer ที่น่าจะมีข้อมูลลูกค้า
LAYERS = {
    "13": "DS_PrimaryMeter",
    "26": "DS_LowVoltageMeter",
    "29": "DS_Pole (PEA_QUERY)",
}

SERVICES = ["PEA", "PEA_QUERY", "PEA_FOR_EXPORT"]

for svc in SERVICES:
    for layer_id, layer_name in LAYERS.items():
        url = (
            f"https://gisne1.pea.co.th/arcgis/rest/services/{svc}/MapServer/{layer_id}"
            "?f=pjson"
        )
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read().decode())
            fields = [f["name"] for f in data.get("fields", [])]
            if "CUSTOMERNAME" in fields:
                print(f"✅ พบ CUSTOMERNAME ใน {svc}/MapServer/{layer_id} ({layer_name})")
            elif fields:
                # แสดง field ที่มีคำว่า customer หรือ name
                matched = [f for f in fields if "CUSTOMER" in f.upper() or "NAME" in f.upper()]
                if matched:
                    print(f"  {svc}/Layer {layer_id}: {matched}")
        except Exception as e:
            pass