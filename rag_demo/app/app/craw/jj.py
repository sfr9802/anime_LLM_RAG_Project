import os
import re
import json
import time
from typing import List, Set
from urllib.parse import unquote, quote
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from pymongo import MongoClient
from pymongo.collection import Collection

# === Mongo 설정 ===

import sys
sys.path.append("G:/port/arin/pp/port/rag_demo/app/app")  # ← 여긴 너 프로젝트의 app 경로

from configure import config


from configure import config

MONGO_URI = os.getenv("mongo_uri", config.MONGO_URL)
DB_NAME = os.getenv("mongo", config.DB_NAME)
COLLECTION_NAME = os.getenv("mgcl", config.COLLECTION_NAME)

_client: MongoClient = None
_collection: Collection = None

def get_mongo_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, maxPoolSize=10)
    return _client

def get_collection() -> Collection:
    global _collection
    if _collection is None:
        client = get_mongo_client()
        _collection = client[DB_NAME][COLLECTION_NAME]
    return _collection

# 업데이트 요청 반영: Mongo 삽입 시 벡터화 상태 및 생성일 포함
# 이미 반영된 형태지만 명시적으로 해당 부분을 강조하여 표시
import os
from pathlib import Path
from datetime import datetime

def write_to_json(title: str, url: str, segments: List[str], out_dir="output"):
    os.makedirs(out_dir, exist_ok=True)
    doc = {
        "title": title,
        "url": url,
        "segments": segments,
        "created_at": datetime.utcnow().isoformat()
    }
    safe_title = title.replace("/", "_")
    path = Path(out_dir) / f"{safe_title}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

def insert_to_mongo(title: str, url: str, segments: List[str]):
    collection = get_collection()
    doc = {
        "title": title,
        "url": url,
        "segments": segments,
        "vectorized": False,  # ✅ 향후 Chroma 벡터화 처리 여부
        "created_at": datetime.utcnow()  # ✅ 문서 생성 타임스탬프
    }
    collection.update_one(
        {"title": title},  # 기존 문서 존재 시
        {"$set": doc},     # 덮어쓰기
        upsert=True        # ✅ 없으면 삽입 (중복 방지)
    )


# === 드라이버 초기화 ===
def init_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--log-level=3")
    return webdriver.Chrome(options=options)

# === 본문 div 추출 ===
def extract_best_div(soup: BeautifulSoup) -> str:
    divs = soup.find_all("div")
    best_div, best_score = None, 0
    for div in divs:
        html = str(div)
        br_count = html.count("<br")
        text = div.get_text(separator="\n").strip()
        score = br_count + len(text)
        if score > best_score and len(text) > 300:
            best_score = score
            best_div = div
    return best_div.get_text(separator="\n").strip() if best_div else None

# === 링크 추출 (quote 적용) ===
def get_sub_links(soup: BeautifulSoup, current_title: str) -> Set[str]:
    from urllib.parse import quote

    def partial_quote(title: str) -> str:
        return quote(title, safe="()!")  # 괄호/느낌표 유지

    base_path = f"/w/{partial_quote(current_title)}"
    sub_links = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if (
            href.startswith(base_path)
            and not any(x in href for x in ["#", ":", "?"])
            and len(href) > len(base_path)
        ):
            sub_links.add("https://namu.wiki" + href)
    return sub_links


# === 텍스트 정제 ===
def rough_filter(text: str) -> str:
    text = re.sub(r'#.*\n?', '', text)
    text = re.sub(r'\d+\s*\.\s*', '', text)
    text = re.sub(r'\[\d+\]', '', text)
    text = re.sub(r'\n{2,}', '\n', text)
    return text.strip()

# === 의미 있는 문장 블럭 추출 ===
def extract_meaningful_chunks(text: str) -> List[str]:
    chunks = text.split('\n')
    return [line.strip() for line in chunks if len(line.strip()) > 60 and "콜라보" not in line and not line.startswith("http")]

# === 실행 ===
seed_title = "장송의 프리렌"
seed_url = "https://namu.wiki/w/" + quote(seed_title)

driver = init_driver()
visited = set()
queue = [seed_url]

while queue:
    url = queue.pop(0)
    if url in visited:
        continue
    visited.add(url)

    print(f"[크롤링] {url}")
    driver.get(url)
    time.sleep(5)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    raw_text = extract_best_div(soup)
    if not raw_text:
        print(f"[실패] 본문 없음: {url}")
        continue

    cleaned = rough_filter(raw_text)
    chunks = extract_meaningful_chunks(cleaned)
    title = unquote(url.replace("https://namu.wiki/w/", ""))
    insert_to_mongo(title, url, chunks)
    print(f"[Mongo 저장 완료] {title} → {len(chunks)}개 chunk")

    sub_links = get_sub_links(soup, title)
    for link in sub_links:
        if link not in visited and link not in queue:
            queue.append(link)

driver.quit()
