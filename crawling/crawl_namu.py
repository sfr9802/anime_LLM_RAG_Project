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
# DB 자격증명은 환경변수에서만 읽는다. 기본값에 비밀번호를 박지 않으며,
# DB 모드(NO_DB=0)에서 환경변수가 비어 있으면 init_db_pools가 명시적으로 실패한다.
NUM_WORKERS    = int(os.getenv('CRAWL_WORKERS', '12'))
MAX_DEPTH      = 2
MIN_CHUNK_LEN  = 50
BASE_URL       = "https://namu.wiki"
MONGO_DB       = os.getenv('CRAWL_MONGO_DB', 'namu_crawl')
MONGO_URI      = os.getenv('MONGO_URI') or f"mongodb://localhost:27017/{MONGO_DB}"
MYSQL_CONFIG   = {
    'user':       os.getenv('CRAWL_MYSQL_USER', 'namu_crawl'),
    'password':   os.getenv('CRAWL_MYSQL_PASSWORD', ''),
    'host':       os.getenv('CRAWL_MYSQL_HOST', 'localhost'),
    'database':   os.getenv('CRAWL_MYSQL_DATABASE', MONGO_DB),
    'charset':    'utf8mb4',
    'collation':  'utf8mb4_unicode_ci',
}
# 파일 출력 전용 모드: DB 호출 스킵
NO_DB          = os.getenv('CRAWL_NO_DB', '1') == '1'
OUTPUT_FILE    = os.getenv('CRAWL_OUTPUT', 'crawled_pages.jsonl')
SEED_FILE      = os.getenv('CRAWL_SEED', 'seed_titles.json')
# 본문 길이 임계값: 추출된 본문이 이보다 짧으면 빈/리캡차 stub으로 간주하고 entry 생성 안 함
MIN_PAGE_LEN   = int(os.getenv('CRAWL_MIN_PAGE_LEN', '500'))
# extract_child_links가 빈 리스트일 때 <candidate>/<keyword> URL을 직접 시도(기본 ON).
# 비용: 시드당 candidates * 6 keywords 만큼 추가 fetch. 끄려면 '0'.
PROBE_SUBPAGES = os.getenv('CRAWL_PROBE_SUBPAGES', '1') == '1'

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
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)

def make_chrome_driver() -> webdriver.Chrome:
    """봇 탐지/리캡차 회피용 stealth 옵션이 적용된 Chrome 드라이버."""
    opts = Options()
    opts.add_argument('--headless=new')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_argument(f'--user-agent={USER_AGENT}')
    opts.add_argument('--lang=ko-KR')
    opts.add_argument('--window-size=1280,900')
    opts.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
    opts.add_experimental_option('useAutomationExtension', False)
    opts.add_argument('--disable-background-networking')
    opts.add_argument('--disable-client-side-phishing-detection')
    opts.add_argument('--disable-default-apps')
    opts.add_argument('--disable-gcm')
    opts.add_argument('--disable-sync')
    opts.add_argument('--metrics-recording-only')

    service = Service(executable_path=DRIVER_PATH, log_path=os.devnull)
    driver = webdriver.Chrome(service=service, options=opts)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"},
        )
    except Exception as e:
        logger.warning(f"CDP webdriver mask failed: {e}")
    return driver

def init_worker(shared_visited):
    global _worker_driver, VISITED
    VISITED = shared_visited
    try:
        _worker_driver = make_chrome_driver()
        logging.getLogger('selenium').setLevel(logging.CRITICAL)
        logger.info(f"Worker driver initialized for process {os.getpid()}")
    except Exception as e:
        logger.error(f"Worker driver init failed: {e}")
        raise

def fetch_soup(url: str) -> Tuple[BS, str]:
    """페이지를 로드하고 (soup, 최종 URL)을 반환.
    최종 URL은 selenium이 따라간 redirect 후 URL이라 호출자가 별칭/리다이렉트를 감지할 수 있다.
    """
    last_err = None
    for attempt in range(2):
        try:
            _worker_driver.get(url)
            time.sleep(random.uniform(2.0, 4.0))
            try:
                toggles = _worker_driver.find_elements(By.XPATH, "//dt[contains(text(),'펼치기')]")[:5]
                for toggle in toggles:
                    _worker_driver.execute_script("arguments[0].scrollIntoView(true);", toggle)
                    toggle.click()
                    time.sleep(0.2)
            except Exception:
                pass
            return BS(_worker_driver.page_source, 'html.parser'), _worker_driver.current_url
        except Exception as e:
            last_err = e
            logger.error(f"Error fetching {url} (try {attempt+1}/2): {e}")
            time.sleep(2.0)
    if last_err:
        raise last_err
    return BS(_worker_driver.page_source, 'html.parser'), _worker_driver.current_url


def _normalize_url(u: str) -> str:
    """비교용 URL 정규화: 앵커/쿼리 제거, 트레일링 슬래시 제거."""
    p = urlparse(u)
    path = p.path.rstrip('/')
    return urlunparse((p.scheme, p.netloc, path, '', '', ''))

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

def _category_prefixes(soup: BS) -> set:
    """페이지 분류(카테고리) 링크에서 슬래시 앞 prefix 토큰을 추출.
    redirect 별칭 시드(예: 짱구는 못말려)에서 정식 명칭(예: 크레용 신짱)을
    candidates에 자동 보강하기 위함.
    예) /w/분류:크레용 신짱/미디어 믹스  -> '크레용 신짱'
        /w/분류:일본 애니메이션/2026년 -> '일본 애니메이션'(무해, 매칭 실패)
    """
    prefixes: set = set()
    for a in soup.find_all('a', href=True):
        href = clean_href(a.get('href', ''))
        if not href.startswith('/w/'):
            continue
        path = unquote(href[len('/w/'):])
        if not path.startswith('분류:'):
            continue
        body = path[len('분류:'):]
        if '/' not in body:
            continue
        head = body.split('/', 1)[0].strip()
        if len(head) >= 2:
            prefixes.add(head)
    return prefixes


def _seed_candidates(seed: str, soup: BS) -> set:
    """sub-page 매칭에 쓸 시드 후보 토큰 집합:
    원본, disambig suffix 제거, og:title/og:url canonical, 분류 prefix를 모두 포함.
    """
    candidates = {seed, clean_title(seed)}
    for prop in ('og:title', 'og:url'):
        m = soup.find('meta', property=prop)
        if not m or not m.has_attr('content'):
            continue
        v = m['content'].strip()
        if prop == 'og:url' and '/w/' in v:
            v = unquote(v.split('/w/', 1)[-1])
        if v:
            candidates.add(v)
            candidates.add(clean_title(v))
    candidates |= _category_prefixes(soup)
    return {c for c in candidates if c}

SUBPAGE_KEYWORDS = ["등장인물", "줄거리", "설정", "회차", "방영", "평가"]


def extract_child_links(soup: BS, seed: str) -> List[Tuple[str, str]]:
    """seed 또는 그 canonical/base 토큰 + 섹션 키워드 형태의 sub-page 링크 추출."""
    candidates = _seed_candidates(seed, soup)
    childs: List[Tuple[str, str]] = []
    seen_paths = set()
    for a in soup.find_all('a', href=True):
        href = clean_href(a['href'])
        if not href.startswith('/w/'):
            continue
        decoded = unquote(href[len('/w/'):])
        parts = decoded.split('/')
        if len(parts) != 2:
            continue
        name, section = parts
        if section not in SUBPAGE_KEYWORDS or name not in candidates:
            continue
        if href in seen_paths:
            continue
        seen_paths.add(href)
        childs.append((section, urljoin(BASE_URL, href)))
    logger.info(f"extract_child_links seed={seed} candidates={sorted(candidates)} -> {childs}")
    return childs


def _probe_subpage_urls(soup: BS, seed: str) -> List[Tuple[str, str]]:
    """3-B: extract_child_links가 비어 있을 때 <candidate>/<keyword> 형태의 URL을
    직접 구성해 sections로 반환. 실제 fetch는 일반 crawl_recursive 경로로 위임되어
    redirect / 본문 길이 검증을 통해 자동 skip된다.
    """
    candidates = _seed_candidates(seed, soup)
    out: List[Tuple[str, str]] = []
    seen = set()
    for cand in candidates:
        for kw in SUBPAGE_KEYWORDS:
            path = f"{cand}/{kw}"
            url = f"{BASE_URL}/w/{quote(path)}"
            if url in seen:
                continue
            seen.add(url)
            out.append((kw, url))
    return out

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

_TITLE_PREFIX_BLOCK = ('파일:', '분류:', '틀:', '나무위키:', '사용자:', '특수기능:')

def _collect_single_token_links(scope: BS) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for a in scope.find_all('a', href=True):
        href = clean_href(a.get('href', ''))
        if not href.startswith('/w/'):
            continue
        path = href.split('/w/', 1)[-1]
        if '/' in path or ':' in path:
            continue
        title = clean_title(path)
        if len(title) < 2 or title.startswith(_TITLE_PREFIX_BLOCK):
            continue
        out.append((title, urljoin(BASE_URL, href)))
    return out

def extract_character_links(soup: BS) -> List[Tuple[str, str]]:
    """등장인물 페이지에서 캐릭터 링크를 구조적으로 추출합니다.
    해시 클래스(예: 빌드마다 회전하는 obfuscated CSS class)에 의존하지 않습니다.
    """
    is_char = is_character_page(soup)

    chars: List[Tuple[str, str]] = []
    for td in soup.find_all('td'):
        chars.extend(_collect_single_token_links(td))

    if is_char:
        chars.extend(_collect_single_token_links(soup))

    seen, unique_chars = set(), []
    for title, link in chars:
        if title not in seen:
            seen.add(title)
            unique_chars.append((title, link))

    logger.info(
        f"{'Full' if is_char else 'Limited'} extraction: "
        f"Found {len(unique_chars)} character links"
    )
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
        soup, final_url = fetch_soup(url)
        pages: List[Dict] = []

        # redirect 감지: depth>0에서 sub-page URL이 다른 페이지로 redirect됐다면
        # 콘텐츠가 요청 의도와 어긋난 것이므로 entry 생성 안 함(시드와 중복/오염 방지).
        sub_redirected = False
        if depth > 0 and _normalize_url(final_url) != _normalize_url(url):
            logger.info(f"Sub-page redirect skip (depth={depth}): {url} -> {final_url}")
            VISITED[final_url] = True
            sub_redirected = True

        # 본문 추출 및 검증
        raw = extract_best_div(soup)
        raw_len = len(raw) if raw else 0
        logger.info(f"Extracted text length: {raw_len}")

        if sub_redirected:
            logger.warning(
                f"Skip entry for {title} (depth={depth}): redirected away from requested sub-page"
            )
        elif raw_len < MIN_PAGE_LEN:
            # 빈 stub / reCAPTCHA 페이지로 간주: entry 생성 안 함.
            # depth 0이면 sub-link 탐색은 계속 진행(redirect/카테고리 prefix를 통해 sub-page를 잡을 수도 있음).
            logger.warning(
                f"Skip entry for {title} (depth={depth}): body too short "
                f"({raw_len} < MIN_PAGE_LEN={MIN_PAGE_LEN})"
            )
        else:
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

        # 하위 링크 처리
        if depth == 0:
            sections = extract_child_links(soup, seed)
            logger.info(f"Seed sections for {seed}: {len(sections)} found - {[s[0] for s in sections]}")
            # 3-B: extract_child_links가 비었을 때 <candidate>/<keyword> URL을 직접 시도.
            # CRAWL_PROBE_SUBPAGES=1일 때만 활성. redirect/짧은 본문은 sub_redirected/MIN_PAGE_LEN으로 자동 skip.
            if not sections and PROBE_SUBPAGES:
                sections = _probe_subpage_urls(soup, seed)
                logger.info(f"Probe-fallback for {seed}: {len(sections)} URL(s) constructed")
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

    if NO_DB:
        return

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

    driver = make_chrome_driver()

    global _worker_driver, VISITED
    _worker_driver = driver
    VISITED = {}
    
    try:
        test_title = os.getenv("DEBUG_TITLE", "귀멸의 칼날")
        test_url = os.getenv("DEBUG_URL", f"{BASE_URL}/w/{quote(test_title)}")
        logger.info(f"DEBUG target: {test_title} -> {test_url}")
        pages = crawl_recursive(test_title, test_url, 0)
        
        logger.info(f"Test crawl result: {len(pages)} pages")
        for i, page in enumerate(pages[:3]):  # 처음 3개만 출력
            logger.info(f"Page {i}: {page['title']} (depth: {page['metadata']['depth']})")
        
        if pages:
            save_pages_safely(pages, "crawl_dryrun.jsonl")
            
    finally:
        driver.quit()

def main():
    # 디버그 모드 설정
    debug_mode = os.getenv('DEBUG', 'false').lower() == 'true'
    if debug_mode:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("Debug mode enabled")
    
    if NO_DB:
        logger.info("NO_DB=1: skipping MySQL/Mongo init (file-only mode)")
    else:
        test_database_connection()
        init_db_pools()
        setup_database()

    # 디버그 모드면 단일 페이지만 테스트
    if debug_mode:
        debug_crawl_single_page()
        return

    # 시드 애니 제목 목록 로드
    try:
        with open(SEED_FILE, encoding="utf-8") as f:
            data: Dict[str, List[str]] = json.load(f)
    except Exception as e:
        logger.error(f"{SEED_FILE} load failed: {e}")
        return

    anime_titles: List[str] = []
    for period in sorted(data.keys()):
        anime_titles.extend(data[period])
    # 중복 제거(여러 쿼터에 같은 작품이 있을 수 있음)
    seen_t = set()
    anime_titles = [t for t in anime_titles if not (t in seen_t or seen_t.add(t))]
    logger.info(f"Loaded {len(anime_titles)} unique seed titles from {SEED_FILE}.")

    test_titles = anime_titles
    tasks = [(t, f"{BASE_URL}/w/{quote(t)}") for t in test_titles]
    output_file = OUTPUT_FILE
    if os.path.exists(output_file):
        logger.info(f"Output file {output_file} already exists; appending (no truncate).")

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
    if NO_DB:
        try:
            with open(output_file, encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
            logger.info(f"Final file count: {line_count} lines in {output_file}")
        except Exception as e:
            logger.error(f"Final file count failed: {e}")
    else:
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