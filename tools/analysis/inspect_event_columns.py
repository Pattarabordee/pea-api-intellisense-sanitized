import pandas as pd

df = pd.read_excel("Event_from_report52_PKN.xlsx")
print("คอลัมน์ทั้งหมด:")
for col in df.columns:
    print(f"  '{col}'")

print("\n5 แถวแรก:")
print(df.head())