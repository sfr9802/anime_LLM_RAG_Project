import pandas as pd
import ast
from pymongo import MongoClient
from tqdm import tqdm
from collections import Counter

# CSV 파일 목록
csv_files = [
    "daum_header 2012.csv",
    "daum_header 2013.csv",
    "daum_header 2014.csv",
    "daum_header 2015.csv",
    "daum_header 2016.csv",
    "daum_header 2017.csv",
    "daum_header 2018.csv",
    "daum_header 2019_0815.csv",
    "daum_header 2019_0816.csv",
    "daum_header 2019_0817_1231.csv",
    "daum_header 2020.csv",
    "daum_header 2021.csv",
    "daum_header 2022.csv",
    "daum_header 220520.csv"
]

# MongoDB 연결
client = MongoClient("mongodb://localhost:27017")
db = client["news_vector_db"]
collection = db["daum_headlines"]
collection.delete_many({})  # 기존 데이터 초기화

# 데이터 파싱 및 저장
inserted_docs = []
year_counter = Counter()

for file_name in csv_files:
    print(f"[처리 중] {file_name}")
    try:
        df = pd.read_csv(file_name, encoding="utf-8", engine="python")
    except Exception as e:
        print(f"  ❌ 파일 로딩 실패: {e}")
        continue

    for _, row in df.iterrows():
        try:
            date = row.get('date') or row.get('Unnamed: 0')
            year = int(str(date)[:4])
            # 리스트 형태의 문자열을 실제 파이썬 리스트로 변환
            headlines = ast.literal_eval(row['header'])
            if not isinstance(headlines, list):
                continue

            for headline in headlines:
                doc = {
                    "title": f"{date} - {headline}",
                    "content": headline,
                    "date": date,
                    "year": year,
                    "source": "daum"
                }
                inserted_docs.append(doc)
                year_counter[year] += 1
        except Exception as e:
            continue  # 문제가 있는 행은 건너뜀

# 몽고에 적재
if inserted_docs:
    collection.insert_many(inserted_docs)

    # 전체 갯수 출력
    print(f"\n✅ 총 저장된 헤드라인 수: {len(inserted_docs):,}개")
    print(f"✅ MongoDB에 저장된 수: {collection.count_documents({}):,}개\n")

    # 연도별 요약 출력
    print("📅 연도별 헤드라인 수:")
    for y in sorted(year_counter):
        print(f"  - {y}년: {year_counter[y]:,}개")

    # 상위 10개 샘플 출력 (10개 미만이어도 안전)
    sample_size = min(10, len(inserted_docs))
    df_sample = pd.DataFrame(inserted_docs[:sample_size])
    print("\n🔎 샘플 데이터:")
    print(df_sample[['title', 'date']])
else:
    print("\n❌ 유효한 헤드라인이 하나도 없습니다.")
