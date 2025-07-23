import os
import json
import time
import random
import re
from typing import List, Set, Dict, Tuple
from urllib.parse import quote, unquote
from datetime import datetime
from multiprocessing import Pool, cpu_count

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# === 설정 ===
MONTHLY_FILE = "anime_titles_clean.json"
OUTPUT_DIR = "output_titles"
BASE_URL = "https://namu.wiki/w/"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36",
]

NOISE_PHRASES = [
    "[편집]", "[새 문서 만들기]", "해당 문서를 찾을 수 없습니다",
    "Contáctenos", "Términos de uso", "Operado por", "Hecho con ❤️",
    "Su zona horaria", "Impulsado por", "protected by reCAPTCHA",
    "protected by hCaptcha", "CC BY", "CC BY-NC-SA"
]

NOISE_REGEX = [r"\d+분 전", r"\d{1,2}월\s*\d{1,2}일"]

def is_noise(line: str) -> bool:
    if any(ph in line for ph in NOISE_PHRASES):
        return True
    if any(re.search(rx, line) for rx in NOISE_REGEX):
        return True
    return False

def enrich_chunks(seed_title: str, page_dict: Dict[str, Dict], created_at: str) -> List[Dict]:
    enriched = []
    for sub_title, page_data in page_dict.items():
        full_text = "\n\n".join(page_data["chunks"])  # 여기만 고치면 됨
        enriched.append({
            "text": full_text,
            "url": page_data["url"],
            "metadata": {
                "seed_title": seed_title,
                "sub_title": sub_title,
                "created_at": created_at,
                "source": "나무위키"
            }
        })
    return enriched


def init_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--log-level=3")
    ua = random.choice(USER_AGENTS)
    opts.add_argument(f"user-agent={ua}")
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

def extract_best_div(soup: BeautifulSoup) -> str:
    best_div, best_score = None, 0
    for div in soup.find_all("div"):
        txt = div.get_text("\n").strip()
        score = txt.count("\n") + len(txt)
        if score > best_score and len(txt) > 200:
            best_score, best_div = score, div
    return best_div.get_text("\n") if best_div else ""

def get_sub_links(soup: BeautifulSoup, current_title: str) -> Set[str]:
    base = f"/w/{quote(current_title)}"
    out: Set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(base) and not any(x in href for x in ["#", ":", "?"]) and len(href) > len(base):
            out.add("https://namu.wiki" + href)
    return out

def extract_chunks_from_raw(raw: str) -> List[str]:
    return [ln.strip() for ln in raw.split("\n") if len(ln.strip()) >= 60 and not is_noise(ln)]

def crawl_title(title: str) -> Tuple[str, List[Dict]]:
    driver = init_driver()
    seed_url = BASE_URL + quote(title)
    visited, queue = set(), [seed_url]
    results: Dict[str, Dict] = {}

    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            time.sleep(random.uniform(1.5, 3.0))
            driver.get(url)
            time.sleep(2)
            soup = BeautifulSoup(driver.page_source, "html.parser")
            raw = extract_best_div(soup)
            if not raw:
                continue
            chunks = extract_chunks_from_raw(raw)
            if not chunks:
                continue
            sub_title = unquote(url.rsplit("/", 1)[-1])
            results[sub_title] = {"url": url, "chunks": chunks}
            for sub in get_sub_links(soup, sub_title):
                if sub not in visited and sub not in queue:
                    queue.append(sub)
        except Exception as e:
            print(f"[ERROR] {title} :: {url} -> {e}")
    driver.quit()
    if not results:
        return title, []
    created_at = datetime.utcnow().isoformat()
    return title, enrich_chunks(title, results, created_at)

def crawl_and_save(title: str):
    try:
        title_clean = title.replace("/", "_")
        out_path = os.path.join(OUTPUT_DIR, f"{title_clean}.json")
        if os.path.exists(out_path):
            print(f"[SKIP] {title}")
            return
        print(f"[CRAWL] {title}")
        title, enriched = crawl_title(title)
        if enriched:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(enriched, f, ensure_ascii=False, indent=2)
            print(f"  ✅ Saved: {title}")
        else:
            print(f"  ⚠️ Empty: {title}")
    except Exception as e:
        print(f"[FAIL] {title} → {e}")

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(MONTHLY_FILE, "r", encoding="utf-8") as f:
        month_map: Dict[str, List[str]] = json.load(f)
    all_titles = sorted({title for titles in month_map.values() for title in titles})

    num_proc = min(6, cpu_count())  # i7-8700 기준 안정 병렬 수
    with Pool(processes=num_proc) as pool:
        pool.map(crawl_and_save, all_titles)

if __name__ == "__main__":
    main()
