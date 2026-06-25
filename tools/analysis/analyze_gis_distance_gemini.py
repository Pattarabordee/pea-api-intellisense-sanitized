import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import re

# กำหนดชื่อไฟล์ Input
INPUT_FILE = "gis_distance.csv"

def guess_device_type(tag):
    """ฟังก์ชันช่วยเดาประเภทอุปกรณ์จากชื่อ Tag"""
    t = str(tag)
    if re.match(r'^21\d{2}XF', t): return 'Transformer (Layer 17)'
    if re.match(r'^21\d{2}SW', t) or re.match(r'^21SW', t): return 'Switch/DOF (Layer 16)'
    if re.match(r'^21\d{2}', t): return 'Recloser (Layer 14)'
    return 'LV Meter (Layer 26)'

def main():
    print(f"Loading data from {INPUT_FILE}...")
    try:
        df = pd.read_csv(INPUT_FILE)
    except FileNotFoundError:
        print(f"Error: ไม่พบไฟล์ {INPUT_FILE} กรุณาตรวจสอบให้แน่ใจว่าอยู่ในโฟลเดอร์เดียวกัน")
        return

    print("\n" + "="*50)
    print(" 1. วิเคราะห์กลุ่มที่หาไม่เจอ (NOT_FOUND)")
    print("="*50)
    
    df_nf = df[df['status'] == 'NOT_FOUND'].copy()
    if not df_nf.empty:
        # เดาประเภทอุปกรณ์
        df_nf['guessed_type'] = df_nf['OpDeviceGIStag'].apply(guess_device_type)
        print(f"จำนวน NOT_FOUND ทั้งหมด: {len(df_nf)} รายการ\n")
        print("แยกตามประเภทอุปกรณ์ที่คาดเดาจากรหัส:")
        print(df_nf['guessed_type'].value_counts().to_string())
        
        # แสดงตัวอย่างที่หาไม่เจอ
        print("\nตัวอย่างรหัสที่หาไม่เจอ (5 รายการแรก):")
        print(df_nf['OpDeviceGIStag'].head(5).tolist())
    else:
        print("ยอดเยี่ยม! ไม่มีอุปกรณ์ใดที่หาไม่เจอ")

    print("\n" + "="*50)
    print(" 2. วิเคราะห์ข้อผิดพลาดด้านระยะทาง (Missing Station Coordinates)")
    print("="*50)
    
    df_ok = df[df['status'] == 'OK']
    df_missing_dist = df_ok[df_ok['distance_km'].isna()]
    if not df_missing_dist.empty:
        print(f"พบอุปกรณ์ที่หาพิกัดเจอ แต่คำนวณระยะทางไม่ได้ {len(df_missing_dist)} รายการ")
        print("เนื่องจากไม่มีพิกัดสถานีต้นทาง (Station Code) ต่อไปนี้ในระบบ:")
        print(df_missing_dist['station_code'].value_counts().to_string())
    else:
        print("อุปกรณ์ที่สถานะ OK สามารถคำนวณระยะทางได้ครบถ้วน")

    print("\n" + "="*50)
    print(" 3. วิเคราะห์ระยะทางที่ไกลผิดปกติ (Outliers > 60 km)")
    print("="*50)
    
    threshold = 60
    df_outliers = df_ok[df_ok['distance_km'] > threshold]
    if not df_outliers.empty:
        print(f"พบอุปกรณ์ที่ระยะทางไกลกว่า {threshold} กม. จำนวน {len(df_outliers)} รายการ")
        print("\nตัวอย่าง 5 รายการที่ไกลที่สุด:")
        print(df_outliers.sort_values(by='distance_km', ascending=False)[['OpDeviceGIStag', 'station_code', 'distance_km', 'layer']].head().to_string(index=False))
    else:
        print(f"ไม่พบอุปกรณ์ที่ระยะทางไกลเกิน {threshold} กม.")

    print("\n" + "="*50)
    print(" 4. กำลังสร้างกราฟ Data Visualization...")
    print("="*50)
    
    df_valid_dist = df_ok.dropna(subset=['distance_km']).copy()
    
    # ตั้งค่าสไตล์กราฟ
    sns.set_theme(style="whitegrid")
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # กราฟที่ 1: Histogram ดูการกระจายตัวของระยะทาง
    sns.histplot(data=df_valid_dist, x='distance_km', bins=30, kde=True, ax=axes[0], color='#2E86C1')
    axes[0].set_title('Distribution of GIS Distances (km)', fontsize=14)
    axes[0].set_xlabel('Distance (km)', fontsize=12)
    axes[0].set_ylabel('Count (Number of Devices)', fontsize=12)

    # กราฟที่ 2: Boxplot แยกตาม Layer
    layer_mapping = {14.0: 'Recloser (14)', 16.0: 'Switch (16)', 17.0: 'Transformer (17)', 26.0: 'Meter (26)'}
    df_valid_dist['Layer_Name'] = df_valid_dist['layer'].map(layer_mapping)
    
    sns.boxplot(data=df_valid_dist, x='Layer_Name', y='distance_km', ax=axes[1], palette="Set2")
    axes[1].set_title('Distance Outliers by Device Layer', fontsize=14)
    axes[1].set_xlabel('GIS Layer', fontsize=12)
    axes[1].set_ylabel('Distance (km)', fontsize=12)

    plt.tight_layout()
    # บันทึกรูปภาพ
    plt.savefig('distance_analysis_plot.png', dpi=300)
    print("บันทึกกราฟลงไฟล์ 'distance_analysis_plot.png' เรียบร้อยแล้ว")
    
    # แสดงกราฟหน้าจอ
    plt.show()

if __name__ == "__main__":
    main()