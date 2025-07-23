from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["ryn"]
col = db["documents"]

total_segments = 0
for doc in col.find():
    segments = doc.get("segments", [])
    total_segments += len(segments)

print(f"📊 전체 segment 수: {total_segments}")
print(f"📄 전체 도큐먼트 수: {col.count_documents({})}")
print(f"📊 평균 segment/도큐먼트: {total_segments / max(col.count_documents({}),1):.2f}")
