import pandas as pd

df = pd.read_csv("daum_header 2012.csv", encoding="utf-8")
print(df.columns)
print(df.head(3))
print("\n🔍 header 필드 예시:")
print(df['header'].iloc[0])
