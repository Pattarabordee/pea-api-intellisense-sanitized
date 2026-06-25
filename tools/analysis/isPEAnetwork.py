import requests

# ทดสอบการเชื่อมต่อ
try:
    res = requests.get("https://gisne1.pea.co.th", timeout=5)
    print("✅ เชื่อมต่อได้ — อยู่ในเครือข่าย PEA")
except Exception as e:
    print("❌ เชื่อมต่อไม่ได้ —", e)