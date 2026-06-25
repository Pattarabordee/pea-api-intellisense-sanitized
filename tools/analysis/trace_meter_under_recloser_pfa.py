import urllib.request
import urllib.parse
import json
import time
import pandas as pd

def fetch_url(url, timeout=60, retries=3):
    """ดึงข้อมูลพร้อม retry อัตโนมัติ"""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            print(f"   Attempt {attempt+1}/{retries} failed: {e}")
            time.sleep(3)  # รอ 3 วินาทีก่อน retry
    return None

def get_recloser_list(keyword):
    encoded = urllib.parse.quote(keyword)
    url = (
        "https://gisne1.pea.co.th/arcgis/rest/services/PEA/MapServer/14/query"
        f"?where=FACILITYID+LIKE+%27{encoded}%25%27"
        "&outFields=FACILITYID"
        "&returnGeometry=true"
        "&f=pjson"
    )
    return fetch_url(url)

def trace_downstream(x, y):
    url = (
        f"http://172.16.184.233/arcgis/rest/services/PEA/MapServer/exts/TraceDownHV_LV/TraceDownHV_LV"
        f"?geometry=%7B%22x%22%3A{x}%2C%22y%22%3A{y}%2C%22spatialReference%22%3A%7B%22wkid%22%3A102100%7D%7D"
        "&f=pjson"
    )
    return fetch_url(url, timeout=120)  # Trace ใช้เวลานาน เพิ่มเป็น 120 วิ

# ===== Main =====
print("Step 1: ดึงรายการ Recloser PFA...")
recloser_data = get_recloser_list("PFA")
reclosers = recloser_data.get("features", [])
print(f"พบ Recloser {len(reclosers)} อัน")

all_meters = []
failed_reclosers = []  # เก็บรายการที่ล้มเหลวไว้ retry ทีหลัง

for i, rc in enumerate(reclosers, 1):
    attr = rc.get("attributes", {})
    geom = rc.get("geometry", {})
    facilityid = attr.get("FACILITYID")
    x = str(geom.get("x", ""))
    y = str(geom.get("y", ""))

    print(f"\n[{i}/{len(reclosers)}] Trace: {facilityid}...")

    trace_data = trace_downstream(x, y)

    if trace_data is None:
        print(f"   ล้มเหลว — เก็บไว้ retry")
        failed_reclosers.append(rc)
        continue

    meter_count = 0
    for layer in trace_data.get("traceResult", []):
        if "DS_LowVoltageMeter" not in layer.get("name", ""):
            continue
        for m in layer.get("features", []):
            m_attr = m.get("attributes", {})
            all_meters.append({
                "RecloserID" : facilityid,
                "PEANO"      : "<redacted>",
                "FEEDERID"   : m_attr.get("FEEDERID"),
                "LOCATION"   : m_attr.get("LOCATION"),
            })
            meter_count += 1

    print(f"   พบมิเตอร์ {meter_count} ลูก | รวมสะสม {len(all_meters)} ลูก")

    # บันทึก checkpoint ทุก 5 Recloser
    if i % 5 == 0:
        df_temp = pd.DataFrame(all_meters)
        df_temp.to_excel(f"checkpoint_recloser_{i}.xlsx", index=False)
        print(f"   Checkpoint saved: checkpoint_recloser_{i}.xlsx")

    time.sleep(1)  # หน่วงเล็กน้อยไม่ให้ Server โหลดหนักเกินไป

# ===== Retry รายการที่ล้มเหลว =====
if failed_reclosers:
    print(f"\nRetry {len(failed_reclosers)} Recloser ที่ล้มเหลว...")
    for rc in failed_reclosers:
        attr = rc.get("attributes", {})
        geom = rc.get("geometry", {})
        facilityid = attr.get("FACILITYID")
        x = str(geom.get("x", ""))
        y = str(geom.get("y", ""))
        print(f"  Retry: {facilityid}...")
        trace_data = trace_downstream(x, y)
        if trace_data:
            for layer in trace_data.get("traceResult", []):
                if "DS_LowVoltageMeter" not in layer.get("name", ""):
                    continue
                for m in layer.get("features", []):
                    m_attr = m.get("attributes", {})
                    all_meters.append({
                        "RecloserID" : facilityid,
                        "PEANO"      : "<redacted>",
                        "FEEDERID"   : m_attr.get("FEEDERID"),
                        "LOCATION"   : m_attr.get("LOCATION"),
                    })

# ===== Export Final =====
print(f"\n{'='*50}")
print(f"รวมมิเตอร์ทั้งหมด: {len(all_meters)} ลูก")
df_final = pd.DataFrame(all_meters)
df_final.to_excel("meter_under_recloser_pfa.xlsx", index=False)
print("Export เสร็จ: meter_under_recloser_pfa.xlsx")
