# === 필수 라이브러리만 ===
import os
import json
import time
import random
import logging
import re
from typing import List, Tuple, Dict
from datetime import datetime
from multiprocessing import Pool, Manager
from urllib.parse import quote, urljoin, urlparse, urlunparse, unquote

import mysql.connector
from mysql.connector import pooling
# 수정된 임포트
from pymongo import MongoClient
from pymongo.operations import ReplaceOne 


from bs4 import BeautifulSoup as BS
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

# 로컬 chromedriver 경로 탐색 (PATH 또는 환경변수)
import shutil
DRIVER_PATH = os.getenv("CHROME_DRIVER_PATH") or shutil.which("chromedriver")
if not DRIVER_PATH:
    raise RuntimeError("chromedriver executable not found. Install it or set CHROME_DRIVER_PATH.")

# === 설정 ===
NUM_WORKERS    = 12
MAX_DEPTH      = 2
MIN_CHUNK_LEN  = 50
BASE_URL       = "https://namu.wiki"
MONGO_DB       = 'namu_crawl'
MONGO_URI      = f"mongodb://raguser:ragpass@localhost:27017/{MONGO_DB}?authSource={MONGO_DB}"
MYSQL_CONFIG   = {
    'user': 'arin',
    'password': 'arin0000',
    'host': 'localhost',
    'database': 'namu_crawl',
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci'
}

# === 등장인물 섹션 키워드 (한글/영어) ===
CHAR_SECTION_KEYWORDS = ["등장인물", "캐릭터", "character"]

# 로그 레벨 억제
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# === DB 및 드라이버 전역 변수 ===
mysql_pool   = None
mongo_client = None
_worker_driver: webdriver.Chrome = None
VISITED: Dict[str,bool] = {}

# === DB 초기화 및 설정 ===
def init_db_pools():
    global mysql_pool, mongo_client
    if mysql_pool is None:
        try:
            mysql_pool = mysql.connector.pooling.MySQLConnectionPool(
                pool_name = "namu_pool",
                pool_size = NUM_WORKERS + 2,
                **MYSQL_CONFIG
            )
            logger.info("MySQL connection pool created")
        except Exception as e:
            logger.error(f"MySQL pool creation failed: {e}")
    
    if mongo_client is None:
        try:
            mongo_client = MongoClient(MONGO_URI)
            # 연결 테스트
            mongo_client.admin.command('ping')
            logger.info("MongoDB connection established")
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")

def setup_database():
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS crawled_pages (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    seed_title VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
                    page_title VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
                    parent_title VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
                    depth INT,
                    url TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
                    fetched_at DATETIME,
                    UNIQUE KEY unique_page (seed_title(191), page_title(191))
                )
            """)
            conn.commit()
            logger.info("MySQL table setup completed")
        finally:
            cursor.close()
            conn.close()
    except Exception as e:
        logger.error(f"Database setup failed: {e}")

# === 저장 함수 ===
def get_mongo_collection():
    global mongo_client
    if mongo_client is None:
        return None
    return mongo_client[MONGO_DB]['pages']

def save_to_mysql(pages: List[Dict]):
    global mysql_pool
    if mysql_pool is None:
        logger.warning("MySQL pool not initialized, skipping MySQL save")
        return
    
    if not pages:
        logger.info("No pages to save to MySQL")
        return
    
    try:
        conn = mysql_pool.get_connection()
        cursor = conn.cursor()
        try:
            saved_count = 0
            for p in pages:
                try:
                    m = p['metadata']
                    logger.debug(f"Inserting page: {p['title']} (seed: {m['seed_title']}, depth: {m['depth']})")
                    
                    cursor.execute(
                        """
                        INSERT INTO crawled_pages
                          (seed_title, page_title, parent_title, depth, url, fetched_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE 
                          fetched_at=VALUES(fetched_at),
                          depth=VALUES(depth),
                          parent_title=VALUES(parent_title)
                        """,
                        (
                            m['seed_title'][:255] if m['seed_title'] else None, 
                            p['title'][:255] if p['title'] else None, 
                            (p.get('parent') or '')[:255], 
                            m['depth'], 
                            p['url'], 
                            datetime.fromisoformat(m['fetched_at']).strftime('%Y-%m-%d %H:%M:%S')
                        )
                    )
                    saved_count += 1
                except Exception as row_error:
                    logger.error(f"Error inserting row {p.get('title', 'unknown')}: {row_error}")
                    continue
            
            conn.commit()
            logger.info(f"MySQL: Successfully saved {saved_count}/{len(pages)} pages")
            
            # 저장 확인을 위한 카운트 쿼리
            cursor.execute("SELECT COUNT(*) FROM crawled_pages")
            total_count = cursor.fetchone()[0]
            logger.info(f"MySQL: Total pages in database: {total_count}")
            
        finally:
            cursor.close()
            conn.close()
    except Exception as e:
        logger.error(f"MySQL save error: {e}")
        import traceback
        logger.error(f"MySQL traceback: {traceback.format_exc()}")

# === save_to_mongo 함수 (전부 교체) ===
def save_to_mongo(pages: List[Dict]):
    # mongo_client는 init_db_pools()에서 생성된 전역 변수여야 합니다
    collection = mongo_client[MONGO_DB]['pages']  

    # upsert용 ReplaceOne operation 리스트
    ops: List[ReplaceOne] = []
    for page in pages:
        ops.append(
            ReplaceOne(
                filter={
                    'title':              page['title'],
                    'url':                page['url'],
                    'metadata.seed_title': page['metadata']['seed_title']
                },
                replacement=page,
                upsert=True
            )
        )

    # 수행할 op이 없으면 바로 반환
    if not ops:
        return

    try:
        result = collection.bulk_write(ops, ordered=False)
        logger.info(
            f"MongoDB bulk_write 완료 — "
            f"matched={result.matched_count}, "
            f"upserted={len(result.upserted_ids)}, "
            f"modified={result.modified_count}"
        )
    except Exception:
        # detailed stacktrace 확인
        logger.error("MongoDB bulk_write 실패", exc_info=True)


# === MongoDB 연결·쓰기 테스트 함수 ===
def test_mongo_connectivity():
    """별도 실행해서 권한/접속 문제 확인용"""
    client = MongoClient(MONGO_URI)
    coll = client[MONGO_DB]['pages']
    print("collection 객체:", coll, type(coll))
    try:
        dummy = {'_test': True, 'time': datetime.now().isoformat()}
        rid = coll.insert_one(dummy).inserted_id
        print("Inserted dummy _id:", rid)
        coll.delete_one({'_id': rid})
        print("삭제까지 성공")
    except Exception:
        import traceback; traceback.print_exc()
        
# === 크롤러 및 헬퍼 함수 ===
def init_worker(shared_visited):
    global _worker_driver, VISITED
    VISITED = shared_visited
    try:
        opts = Options()
        opts.add_argument('--headless')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        opts.add_experimental_option('excludeSwitches', ['enable-logging'])
        opts.add_argument('--disable-background-networking')
        opts.add_argument('--disable-client-side-phishing-detection')
        opts.add_argument('--disable-default-apps')
        opts.add_argument('--disable-gcm')
        opts.add_argument('--disable-sync')
        opts.add_argument('--metrics-recording-only')
        opts.add_argument('--disable-features=NetworkService,NetworkServiceInProcess')

        service = Service(executable_path=DRIVER_PATH, log_path=os.devnull)
        _worker_driver = webdriver.Chrome(service=service, options=opts)
        logging.getLogger('selenium').setLevel(logging.CRITICAL)
        logger.info(f"Worker driver initialized for process {os.getpid()}")
    except Exception as e:
        logger.error(f"Worker driver init failed: {e}")
        raise

def fetch_soup(url: str) -> BS:
    try:
        _worker_driver.get(url)
        time.sleep(random.uniform(1, 3))
        try:
            toggles = _worker_driver.find_elements(By.XPATH, "//dt[contains(text(),'펼치기')]")[:5]
            for toggle in toggles:
                _worker_driver.execute_script("arguments[0].scrollIntoView(true);", toggle)
                toggle.click()
                time.sleep(0.2)
        except:
            pass
        return BS(_worker_driver.page_source, 'html.parser')
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        raise

def remove_noise(soup: BS):
    for sel in ['aside','script','footer','header','nav','div[class*="ad"]','iframe']:
        for elem in soup.select(sel):
            elem.decompose()
# ==================== RAG 전처리 ====================
LICENSE_NOISE_PATTERNS = [
    r'(©|\(C\)|ⓒ)\s?.*', r'저작권.*(소유|보유)', r'All\s+Rights\s+Reserved',
    r'방송[일|시간]|방영|재방송', r'[0-9]{4}\.\s?[0-9]{1,2}\.\s?[0-9]{1,2}', 
    r'[0-9]{4}년\s?[0-9]{1,2}월\s?[0-9]{1,2}일',
    r'애니플러스|라프텔|넷플릭스|디즈니\+?|티빙|왓챠|쿠팡플레이',
    r'(Amazon\s+Prime|Hulu|Crunchyroll|Funimation|Netflix)',
    r'(YouTube|TikTok|Twitter|X\s?\(구\s?Twitter\)|인스타그램|Facebook)',
    r'성우\s?[가-힣]+', r'(감독|각본|작화|원작|제작|연출)\s?:?\s?.*',
    r'콜라보|콜라보레이션|이벤트|캠페인|프로모션|행사',
    r'한정\s?(판|수량)|특전|사은품|사인회|전시회',
    r'OST|엔딩|오프닝|ED\s?테마|OP\s?테마', r'(노래|가사)\s?:?\s?.*',
    r'♪.*', r'가사\s?전문', r'작사|작곡|편곡',
    r'(피규어|굿즈|블루레이|DVD|CD|앨범|한정판)',
    r'(플레이스테이션|닌텐도|Xbox|Steam|Switch)',
    r'https?:\/\/[^\s]+', r'www\.[^\s]+',
    r'이 문서의 내용 중 전체 또는 일부는.*', r'에 따라 이용할 수 있습니다.*',
    r'기여하신 문서의 저작권.*', r'나무위키는 백과사전이 아니며.*',
    r'나무위키는 위키위키입니다.*', r'이 문서가 설명하는.*줄거리.*포함하고 있습니다.*',
]

def clean_chunk_text(text: str) -> str:
    """청크 텍스트에서 노이즈 제거"""
    for pat in LICENSE_NOISE_PATTERNS:
        text = re.sub(pat, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def get_character_links_strict(soup: BS) -> List[Tuple[str,str]]:
    a = soup.find('a', href=re.compile(r'/w/.+/등장인물'))
    if not a:
        return []
    container = a.find_parent(['div','dl'])
    if not container:
        return []
    chars, seen = [], set()
    for link in container.find_all('a', href=re.compile(r'^/w/[^/]+$'), title=True):
        name = link['title'].strip()
        url  = urljoin(BASE_URL, link['href'])
        if name not in seen:
            seen.add(name)
            chars.append((name, url))
    logger.info(f"[Strict] found {len(chars)} character links")
    return chars

def extract_best_div(soup: BS) -> str:
    remove_noise(soup)
    best, score = None, 0
    for tag in soup.find_all(['div','table']):
        txt = tag.get_text("\n").strip()
        sc  = len(txt) + txt.count("\n")
        if sc > score and len(txt) > MIN_CHUNK_LEN:
            best, score = tag, sc
    return best.get_text("\n\n").strip() if best else ''

def clean_href(href: str) -> str:
    """앵커(#)와 파라미터(?)를 제거하고 순수 path를 반환합니다."""
    return href.split('#')[0].split('?')[0]

def clean_title(raw: str) -> str:
    """URL 디코딩 후 괄호 내용 제거"""
    text = unquote(raw)
    return re.sub(r"\([^)]*\)$", "", text).strip()

def extract_child_links(soup: BS, seed: str) -> List[Tuple[str, str]]:
    """
    '줄거리', '설정', '회차', '방영', '평가' 섹션 링크를 추출합니다.
    정확히 seed/{section} 형태의 링크만 포함하며, fallback을 제거합니다.
    """
    keywords = ["등장인물", "줄거리", "설정", "회차", "방영", "평가"]
    childs: List[Tuple[str, str]] = []
    for a in soup.find_all('a', href=True):
        href = clean_href(a['href'])
        if not href.startswith('/w/'):
            continue
        raw_path = href[len('/w/'):]
        decoded = unquote(raw_path)
        parts = decoded.split('/')
        if len(parts) != 2:
            continue
        name, section = parts
        if name == seed and section in keywords:
            childs.append((section, urljoin(BASE_URL, href)))
    logger.info(f"extract_child_links for seed={seed} -> {childs}")
    return childs

def is_character_page(soup: BS, url: str = None) -> bool:
    """페이지가 캐릭터 관련 페이지인지 확인합니다."""
    if url and '/등장인물' in url:
        return True
    
    span = soup.find('span', string='분류')
    if span:
        ul = span.find_next_sibling('ul')
        if ul:
            cats = [a.get_text(strip=True) for a in ul.find_all('a')]
            if any('등장인물' in c for c in cats):
                return True
    
    title_tags = soup.find_all(['h1', 'h2', 'h3', 'title'])
    for tag in title_tags:
        text = tag.get_text().lower()
        if any(keyword in text for keyword in ['등장인물', '캐릭터', 'character']):
            return True
    
    return False

def extract_character_links(soup: BS) -> List[Tuple[str, str]]:
    """등장인물 페이지에서 캐릭터 링크를 추출합니다."""
    chars: List[Tuple[str, str]] = []
    
    if not is_character_page(soup):
        logger.info("Not a character page based on category, limiting extraction")
        
        detail_links = soup.find_all('a', class_='pJUgH6Pv')
        for link in detail_links:
            href = link.get('href', '')
            if href.startswith('/w/'):
                href = clean_href(href)
                title = clean_title(href.split('/w/')[-1])
                if title and len(title) >= 2:
                    chars.append((title, urljoin(BASE_URL, href)))
        
        seen = set()
        unique_chars: List[Tuple[str, str]] = []
        for title, link in chars:
            if title not in seen:
                seen.add(title)
                unique_chars.append((title, link))
        
        logger.info(f"Limited extraction: Found {len(unique_chars)} links")
        return unique_chars
    
    logger.info("Confirmed character page, performing full extraction")
    
    detail_links = soup.find_all('a', class_='pJUgH6Pv')
    for link in detail_links:
        href = link.get('href', '')
        if href.startswith('/w/'):
            href = clean_href(href)
            title = clean_title(href.split('/w/')[-1])
            if title and len(title) >= 2:
                chars.append((title, urljoin(BASE_URL, href)))
    
    for td in soup.find_all('td'):
        for a in td.find_all('a', href=True):
            href = a.get('href', '')
            if href.startswith('/w/'):
                href = clean_href(href)
                path_part = href.split('/w/')[-1]
                if '/' in path_part:
                    continue
                title = clean_title(path_part)
                if title and len(title) >= 2:
                    chars.append((title, urljoin(BASE_URL, href)))
    
    for a in soup.find_all('a', href=True):
        href = a.get('href', '')
        if href.startswith('/w/'):
            href = clean_href(href)
            path_part = href.split('/w/')[-1]
            if '/' in path_part or ':' in path_part:
                continue
            title = clean_title(path_part)
            if title and len(title) >= 2 and not title.startswith(('파일:', '분류:', '틀:')):
                chars.append((title, urljoin(BASE_URL, href)))
    
    seen = set()
    unique_chars: List[Tuple[str, str]] = []
    for title, link in chars:
        if title not in seen:
            seen.add(title)
            unique_chars.append((title, link))
    
    logger.info(f"Full extraction: Found {len(unique_chars)} character links")
    return unique_chars

def extract_chunks(text: str, min_len=MIN_CHUNK_LEN, max_len=300) -> List[str]:
    """
    원본 텍스트를 줄 단위로 쪼개고, 
    각 청크에 clean_chunk_text를 적용하여 노이즈를 제거한 뒤 반환합니다.
    """
    raw_lines = [ln.strip() for ln in text.split("\n") if len(ln.strip()) >= min_len]
    chunks: List[str] = []
    for ln in raw_lines:
        if len(ln) <= max_len:
            cleaned = clean_chunk_text(ln)
            if len(cleaned) >= min_len:
                chunks.append(cleaned)
        else:
            # 너무 길면 max_len 단위로 분할
            for i in range(0, len(ln), max_len):
                part = ln[i:i+max_len].strip()
                cleaned = clean_chunk_text(part)
                if len(cleaned) >= min_len:
                    chunks.append(cleaned)
    # 중복 제거
    return list(dict.fromkeys(chunks))

def crawl_recursive(
    title: str,
    url: str,
    depth: int = 0,
    parent: str = None,
    seed: str = None
) -> List[Dict]:
    """
    depth 0: seed 페이지 본문 및 주요 섹션 링크 추출(줄거리, 설정, 회차, 방영, 평가)
    depth 1: 등장인물 페이지 본문 저장 및 캐릭터 링크 추출
    depth 2: 캐릭터 페이지 본문 저장 후 종료
    """
    try:
        if VISITED.get(url):
            logger.debug(f"Already visited: {url}")
            return []
        VISITED[url] = True

        if depth == 0:
            seed = title

        logger.info(f"Crawling: {title} (depth={depth}, url={url})")
        soup = fetch_soup(url)
        pages: List[Dict] = []

        # 본문 추출 및 검증
        raw = extract_best_div(soup)
        logger.info(f"Extracted text length: {len(raw) if raw else 0}")
        
        if raw:
            chunks = extract_chunks(raw)
            logger.info(f"Generated chunks: {len(chunks)}")
            
            if chunks:
                entry = {
                    'title': title,
                    'url': url,
                    'parent': parent,
                    'metadata': {
                        'seed_title': seed,
                        'depth': depth,
                        'fetched_at': datetime.now().isoformat()
                    }
                }
                if depth < 2:
                    entry['chunks'] = chunks
                    logger.info(f"Created entry with {len(chunks)} chunks for {title}")
                else:
                    entry['content'] = raw
                    logger.info(f"Created entry with content ({len(raw)} chars) for {title}")
                pages.append(entry)
            else:
                logger.warning(f"No chunks generated for {title}")
        else:
            logger.warning(f"No content extracted for {title}")

        # 하위 링크 처리
        if depth == 0:
            sections = extract_child_links(soup, seed)
            logger.info(f"Seed sections for {seed}: {len(sections)} found - {[s[0] for s in sections]}")
            for sec_title, sec_url in sections:
                try:
                    sub_pages = crawl_recursive(sec_title, sec_url, 1, title, seed)
                    logger.info(f"Section {sec_title} returned {len(sub_pages)} pages")
                    pages.extend(sub_pages)
                except Exception as e:
                    logger.error(f"Error crawling section {sec_title}: {e}")

        elif depth == 1:
            chars = extract_character_links(soup)
            logger.info(f"Character links on {title}: {len(chars)} found")
            # 캐릭터 링크가 너무 많으면 제한 (테스트용)
            limited_chars = chars[:10] if len(chars) > 10 else chars
            if len(chars) > 10:
                logger.info(f"Limiting character crawling to first 10 out of {len(chars)}")
                
            for char_name, char_url in limited_chars:
                try:
                    char_pages = crawl_recursive(char_name, char_url, 2, title, seed)
                    logger.info(f"Character {char_name} returned {len(char_pages)} pages")
                    pages.extend(char_pages)
                except Exception as e:
                    logger.error(f"Error crawling character {char_name}: {e}")
        
        logger.info(f"Crawl complete for {title}: returning {len(pages)} total pages")
        return pages
        
    except Exception as e:
        logger.error(f"Error in crawl_recursive for {title}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return []

def save_pages_safely(pages: List[Dict], output_file: str):
    """페이지를 안전하게 저장하는 함수"""
    if not pages:
        logger.info("No pages to save")
        return
    
    logger.info(f"Attempting to save {len(pages)} pages...")
    
    # 파일 저장
    try:
        with open(output_file, 'a', encoding="utf-8") as f:
            for p in pages:
                f.write(json.dumps(p, ensure_ascii=False) + '\n')
        logger.info(f"File: Saved {len(pages)} pages to {output_file}")
    except Exception as e:
        logger.error(f"File save error: {e}")
    
    # MySQL 저장
    try:
        save_to_mysql(pages)
    except Exception as e:
        logger.error(f"MySQL save failed: {e}")
    
    # MongoDB 저장
    try:
        save_to_mongo(pages)
    except Exception as e:
        logger.error(f"MongoDB save failed: {e}")

def test_database_connection():
    """데이터베이스 연결 테스트 함수"""
    logger.info("Testing database connections...")
    
    # MySQL 테스트
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        logger.info("MySQL connection test: SUCCESS")
    except Exception as e:
        logger.error(f"MySQL connection test failed: {e}")
    
    # MongoDB 테스트
    try:
        client = MongoClient(MONGO_URI)
        client.admin.command('ping')
        logger.info("MongoDB connection test: SUCCESS")
        client.close()
    except Exception as e:
        logger.error(f"MongoDB connection test failed: {e}")

def debug_crawl_single_page():
    """단일 페이지 크롤링 테스트"""
    logger.info("Testing single page crawl...")
    
    # 간단한 테스트용 드라이버 생성
    opts = Options()
    opts.add_argument('--headless')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    
    service = Service(executable_path=DRIVER_PATH, log_path=os.devnull)
    driver = webdriver.Chrome(service=service, options=opts)
    
    global _worker_driver, VISITED
    _worker_driver = driver
    VISITED = {}
    
    try:
        # 간단한 페이지 테스트
        test_url = f"{BASE_URL}/w/원피스"
        pages = crawl_recursive("원피스", test_url, 0)
        
        logger.info(f"Test crawl result: {len(pages)} pages")
        for i, page in enumerate(pages[:3]):  # 처음 3개만 출력
            logger.info(f"Page {i}: {page['title']} (depth: {page['metadata']['depth']})")
        
        if pages:
            save_pages_safely(pages, "test_crawl.jsonl")
            
    finally:
        driver.quit()

def main():
    # 디버그 모드 설정
    debug_mode = os.getenv('DEBUG', 'false').lower() == 'true'
    if debug_mode:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("Debug mode enabled")
    
    # DB 연결 테스트
    test_database_connection()
    
    # DB 초기화
    init_db_pools()
    setup_database()
    
    # 디버그 모드면 단일 페이지만 테스트
    if debug_mode:
        debug_crawl_single_page()
        return

    # 시드 애니 제목 목록 로드
    try:
        with open("anime_titles_clean.json", encoding="utf-8") as f:
            data: Dict[str, List[str]] = json.load(f)
    except Exception as e:
        logger.error(f"anime_titles_clean.json load failed: {e}")
        return

    anime_titles: List[str] = []
    for period in sorted(data.keys()):
        anime_titles.extend(data[period])
    logger.info(f"Loaded {len(anime_titles)} seed titles.")

    # 테스트를 위해 처음 5개만 크롤링
    test_titles = anime_titles  # 전체 크롤링시에는 anime_titles로 변경
    logger.info(f"Testing with {len(test_titles)} titles: {test_titles}")

    tasks = [(t, f"{BASE_URL}/w/{quote(t)}") for t in test_titles]
    output_file = "crawled.jsonl"
    if os.path.exists(output_file):
        os.remove(output_file)

    manager = Manager()
    shared_visited = manager.dict()
    
    try:
        with Pool(min(NUM_WORKERS, len(test_titles)), initializer=init_worker, initargs=(shared_visited,)) as pool:
            results = pool.starmap(crawl_recursive, tasks)
            for i, pages in enumerate(results):
                task_title = test_titles[i]
                logger.info(f"Task '{task_title}' completed: {len(pages)} pages returned")
                
                if pages:
                    # 페이지 구조 확인
                    logger.info(f"Sample page structure: title='{pages[0]['title']}', depth={pages[0]['metadata']['depth']}")
                    save_pages_safely(pages, output_file)
                else:
                    logger.warning(f"Task '{task_title}' returned no pages!")
    except Exception as e:
        logger.error(f"Pool execution error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        # 드라이버 정리
        try:
            if _worker_driver:
                _worker_driver.quit()
        except:
            pass

    # 최종 결과 확인
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM crawled_pages")
        total_count = cursor.fetchone()[0]
        cursor.execute("SELECT seed_title, COUNT(*) as cnt FROM crawled_pages GROUP BY seed_title ORDER BY cnt DESC LIMIT 10")
        top_seeds = cursor.fetchall()
        cursor.close()
        conn.close()
        
        logger.info(f"Final MySQL count: {total_count} total pages")
        logger.info(f"Top seeds: {top_seeds}")
    except Exception as e:
        logger.error(f"Final count check failed: {e}")

    logger.info("크롤링 완료")

if __name__ == "__main__":
    main()