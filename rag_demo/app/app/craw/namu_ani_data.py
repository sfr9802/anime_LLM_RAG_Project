import os
import json
import time
import random
import re
from typing import List, Set, Dict, Tuple
from urllib.parse import quote, unquote
from datetime import datetime
from multiprocessing import Pool, cpu_count

from bs4 import BeautifulSoup as _BS
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# === 설정 ===
OUTPUT_DIR = "output_titles"
BASE_URL = "https://namu.wiki/w/"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36",
]
MAX_PAGINATED_PAGES = 70
NOISE_PHRASES = [
    "[편집]", "[새 문서 만들기]", "해당 문서를 찾을 수 없습니다",
    "Contáctenos", "Términos de uso", "Operado por", "Hecho con ❤️",
    "Su zona horaria", "Impulsado por", "protected by reCAPTCHA",
    "protected by hCaptcha", "CC BY", "CC BY-NC-SA"
]
NOISE_REGEX = [r"\d+분 전", r"\d{1,2}월\s*\d{1,2}일"]

# === 유효한 파일명으로 치환 ===
def sanitize_filename(name: str) -> str:
    # Windows에서 금지된 문자 제거: < > : " / \ | ? *
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    # 파일명 끝의 공백 및 점 제거
    return name.strip(' .')

# === Selenium Driver 초기화 ===
def init_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--log-level=3")
    opts.add_argument(f"user-agent={random.choice(USER_AGENTS)}")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

# === 페이지네이션된 리스트에서 '다음' 버튼 찾기 ===
def get_true_next_button(driver):
    buttons = driver.find_elements(By.CSS_SELECTOR, "a.ajxp5MEC")
    for btn in reversed(buttons):
        if btn.text.strip() == "다음" and btn.is_displayed():
            return btn
    return None

# === 페이지네이션된 리스트에서 모든 제목 수집 ===
def get_all_titles_from_paginated_list(start_url: str) -> List[str]:
    driver = init_driver()
    encoded_url = quote(start_url, safe=":/?=&%")
    driver.get(encoded_url)
    time.sleep(3)
    titles = set()
    page = 1
    while True:
        soup = _BS(driver.page_source, "html.parser")
        for a in soup.find_all("a", href=True):
            text = a.get_text().strip()
            if 3 < len(text) < 100 and ":" not in text and "/" not in text:
                titles.add(text)
        if page >= MAX_PAGINATED_PAGES:
            break
        btn = get_true_next_button(driver)
        if btn:
            btn.click()
            page += 1
            time.sleep(3)
        else:
            break
    driver.quit()
    return sorted(titles)

# === 노이즈 제거 ===
def remove_noise_sections(soup: _BS):
    selectors = [
        'aside', 'div.namu-news', 'div[data-module="news"]', 'div.aside_news',
        'div[class*="ad"]', 'div[id*="ad"]', 'section.ad'
    ]
    for sel in selectors:
        for node in soup.select(sel):
            node.decompose()

    # 불필요 링크 제거
    for a in soup.select('a[rel~="noopener"], a[href^="/Go"], a[href="/RecentChanges"], a[href^="#s-"]'):
        a.decompose()

    # Creative Commons 라이선스 블록 제거
    for lic in soup.select('a[rel="license"]'):
        div = lic.find_parent('div')
        if div:
            div.decompose()
    for img in soup.select('img[alt="크리에이티브 커먼즈 라이선스"]'):
        div = img.find_parent('div')
        if div:
            div.decompose()

    # 보호 문구 삭제
    for p in soup.find_all('p'):
        text = p.get_text()
        if 'protected by reCAPTCHA' in text or 'protected by hCaptcha' in text:
            div = p.find_parent('div')
            if div:
                div.decompose()

    # 분류 및 타임존 제거
    for span in soup.find_all('span'):
        txt = span.get_text(strip=True)
        if txt in ['분류', 'Asia/Seoul']:
            div = span.find_parent('div')
            if div:
                div.decompose()

    # 최근 변경 목록 제거
    for time_tag in soup.find_all('time', datetime=True):
        ul = time_tag.find_parent('ul')
        if ul:
            ul.decompose()

    # 광고 iframe 및 스크립트 제거
    for node in soup.select('[id*="google_ads_iframe"], ins.adsbygoogle, iframe[src*="ads"], script[src*="adsbygoogle.js"]'):
        node.decompose()

# === 노이즈 라인 판별 ===
def is_noise(line: str) -> bool:
    if any(ph in line for ph in NOISE_PHRASES):
        return True
    if any(re.search(rx, line) for rx in NOISE_REGEX):
        return True
    return False

# === 주요 컨텐츠 추출 ===
def extract_best_div(soup: _BS) -> str:
    info = soup.find('table', class_='infobox')
    if info:
        t = info.get_text("\n").strip()
        if t:
            return t
    remove_noise_sections(soup)
    best, score = None, 0
    for tag in soup.find_all(["div", "table"]):
        txt = tag.get_text("\n").strip()
        sc = len(txt) + txt.count("\n")
        if sc > score and len(txt) > 10:
            score, best = sc, tag
    return best.get_text("\n") if best else ""

# === 텍스트 청크 분리 ===
def extract_chunks_from_raw(raw: str) -> List[str]:
    return [ln.strip() for ln in raw.split("\n")
            if len(ln.strip()) >= 10 and not is_noise(ln)]

# === 메타데이터 포함하여 청크 정리 ===
def enrich_chunks(seed: str, pages: Dict[str, Dict], created: str) -> List[Dict]:
    out = []
    for sub, data in pages.items():
        out.append({
            "text": "\n\n".join(data["chunks"]),
            "url": data["url"],
            "metadata": {
                "seed_title": seed,
                "sub_title": sub,
                "created_at": created,
                "source": "나무위키",
                "llm_summary": ""
            }
        })
    return out

# === 단일 제목 크롤링 ===
def crawl_title(title: str) -> Tuple[str, List[Dict]]:
    driver = init_driver()
    seed_url = BASE_URL + quote(title)
    pages_to_try = [seed_url]
    results: Dict[str, Dict] = {}
    for url in pages_to_try:
        try:
            encoded = quote(url, safe=":/?=&%")
            driver.get(encoded)
            time.sleep(2)
            soup = _BS(driver.page_source, "html.parser")
            raw = extract_best_div(soup)
            if not raw:
                continue
            chunks = extract_chunks_from_raw(raw)
            if not chunks:
                continue
            sub = unquote(url.rsplit('/', 1)[-1])
            results[sub] = {"url": url, "chunks": chunks}
        except Exception:
            continue
    driver.quit()
    created = datetime.utcnow().isoformat()
    if results:
        return title, enrich_chunks(title, results, created)
    return title, []

# === 크롤링 및 저장 ===
def crawl_and_save(title: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_title = sanitize_filename(title)
    filename = f"{safe_title}.json"
    path = os.path.join(OUTPUT_DIR, filename)
    if os.path.exists(path):
        print(f"[SKIP] {title} (already exists)")
        return
    print(f"[CRAWL] {title}")
    _, data = crawl_title(title)
    if data:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[SAVED] {title}")
    else:
        print(f"[EMPTY] {title}")

# === 분기별 페이지에서 제목 추출 ===
def get_titles_from_category_page(category_url: str) -> List[str]:
    driver = init_driver()
    encoded = quote(category_url, safe=":/?=&%")
    driver.get(encoded)
    time.sleep(3)
    soup = _BS(driver.page_source, "html.parser")
    titles = []
    content = soup.find('div', {'class': 'wiki-body'}) or soup.find('article') or soup
    for ul in content.find_all('ul'):
        for li in ul.find_all('li'):
            text = li.get_text().strip()
            if text and ':' not in text:
                titles.append(text)
    driver.quit()
    return sorted(set(titles))

# === 메인 실행부 ===
def main():
    years = range(2006, 2026)
    quarters = [1, 2, 3, 4]
    quarter_links = []
    for year in years:
        for q in quarters:
            raw_title = f"분류:{year}년 {q}분기 일본 애니메이션"
            path = quote(raw_title, safe=":")
            url = BASE_URL + path
            display_title = raw_title.replace("분류:", "")
            quarter_links.append((display_title, url))

    all_titles: Set[str] = set()
    for quarter, url in quarter_links:
        print(f"▶ {quarter} 페이지에서 애니 제목 추출 중...")
        titles = get_titles_from_category_page(url)
        print(f"   - 수집된 제목: {len(titles)}개")
        all_titles.update(titles)

    sorted_titles = sorted(all_titles)
    with Pool(min(6, cpu_count())) as pool:
        pool.map(crawl_and_save, sorted_titles)

if __name__ == '__main__':
    main()
