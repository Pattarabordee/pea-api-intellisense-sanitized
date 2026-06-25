import pandas as pd

# อ่านโดยข้าม header row แรก
df = pd.read_excel("Event_from_report52_PKN.xlsx", header=1)

print("คอลัมน์ทั้งหมด:")
for col in df.columns:
    print(f"  '{col}'")

print(f"\nจำนวนแถว: {len(df)}")
print("\n3 แถวแรก:")
print(df.head(3))