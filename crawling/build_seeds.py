# -*- coding: utf-8 -*-
"""
나무위키 분기별 애니메이션 목록 페이지를 순회하여 시드 제목 리스트를 새로 작성.

기본 출력: anime_titles_clean_v2.json (기존 anime_titles_clean.json 보존)
환경변수:
  SEED_START   기본 "2006-01"
  SEED_END     기본 "2026-04"
  SEED_OUTPUT  기본 "anime_titles_clean_v2.json"
  CHROME_DRIVER_PATH  드라이버 경로(없으면 PATH에서 탐색)

사용:
  python build_seeds.py
  SEED_START=2025-01 SEED_END=2026-04 python build_seeds.py
"""
import os
import re
import json
import time
import shutil
import logging
from typing import Dict, List
from urllib.parse import quote, unquote
from collections import OrderedDict

from bs4 import BeautifulSoup as BS
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

DRIVER_PATH = os.getenv("CHROME_DRIVER_PATH") or shutil.which("chromedriver")
if not DRIVER_PATH:
    raise RuntimeError("chromedriver executable not found. Install it or set CHROME_DRIVER_PATH.")

BASE_URL = "https://namu.wiki"
START   = os.getenv("SEED_START",  "2006-01")
END     = os.getenv("SEED_END",    "2026-04")
OUTPUT  = os.getenv("SEED_OUTPUT", "anime_titles_clean_v2.json")
RENDER_WAIT = float(os.getenv("SEED_RENDER_WAIT", "2.5"))

META_TOKENS = {
    # 카테고리/페이지 메타 (명백)
    "애니메이션", "일본 애니메이션", "한국 애니메이션", "미국 애니메이션",
    "중국 애니메이션", "북한 애니메이션", "유럽 애니메이션",
    "애니메이션/목록", "분류", "특수기능", "나무위키",
    "최근 변경", "최근 토론",
    # 포맷/형식
    "TVA", "OVA", "ONA", "TVS", "극장판", "극장판 애니메이션", "WEB 애니메이션",
    # 국가 (단독 토큰으로 등장하는 인덱스 헤더)
    "일본", "대한민국", "한국", "미국", "중국", "홍콩", "대만", "북한",
    # === 방송국 / OTT (작품이 아닌 배급/방영처) ===
    # 한국 지상파·종편·케이블
    "문화방송", "MBC", "KBS", "EBS", "SBS", "JTBC", "tvN", "OCN", "MBN",
    "TV조선", "채널A", "JEI 재능TV", "어린이TV",
    # 일본 지상파·BS·CS·로컬
    "NHK", "TV 도쿄", "도쿄 MX", "후지테레비", "일본테레비", "닛테레",
    "TBS", "테레비 아사히", "테레비 아이치", "아사히 방송 테레비",
    "메자마시 테레비", "BS 닛테레", "BS 후지", "BS 아사히", "BS-TBS",
    "BS11", "BS12", "MBS", "AT-X", "tvk",
    # OTT / 스트리밍
    "텐센트 비디오", "U-NEXT", "ABEMA", "TVING", "FOD", "라프텔",
    "넷플릭스", "Netflix", "디즈니+", "디즈니플러스", "티빙", "왓챠",
    "쿠팡플레이", "Crunchyroll", "Funimation", "Hulu", "YouTube",
}
TITLE_PREFIX_BLOCK = ('파일:', '분류:', '틀:', '나무위키:', '사용자:', '특수기능:', 'r:')

# 정리: 연도/숫자만 또는 너무 짧은 제목, 알파벳 1글자, 한글 1글자 제외
RE_NUM_ONLY = re.compile(r'^\d+$')
RE_YEAR_LIKE = re.compile(r'^\d{4}년( \d{1,2}월)?$')
# disambig suffix가 작품이 아닌 메타(만화/잡지/소설)일 때 차단
RE_SUFFIX_NOISE = re.compile(r'\((만화|잡지|소설)\)\s*$')

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("build_seeds")


def quarters(start: str, end: str) -> List[str]:
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out: List[str] = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 3
        if m > 12:
            m -= 12
            y += 1
    return out


def build_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument('--headless')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_experimental_option('excludeSwitches', ['enable-logging'])
    opts.add_argument('--disable-background-networking')
    opts.add_argument('--disable-client-side-phishing-detection')
    opts.add_argument('--disable-default-apps')
    opts.add_argument('--disable-features=NetworkService,NetworkServiceInProcess')
    service = Service(executable_path=DRIVER_PATH, log_path=os.devnull)
    return webdriver.Chrome(service=service, options=opts)


def fetch_titles(driver: webdriver.Chrome, year: int, month: int) -> List[str]:
    path = f"애니메이션/{year}년 {month}월"
    url = f"{BASE_URL}/w/{quote(path)}"
    driver.get(url)
    time.sleep(RENDER_WAIT)
    soup = BS(driver.page_source, 'html.parser')

    titles: "OrderedDict[str, None]" = OrderedDict()
    for a in soup.find_all('a', href=True):
        href = a.get('href', '').split('#', 1)[0].split('?', 1)[0]
        if not href.startswith('/w/'):
            continue
        path_part = href[len('/w/'):]
        if '/' in path_part or ':' in path_part:
            continue
        title = unquote(path_part).strip()
        if len(title) < 2:
            continue
        if title in META_TOKENS:
            continue
        if title.startswith(TITLE_PREFIX_BLOCK):
            continue
        if RE_NUM_ONLY.fullmatch(title) or RE_YEAR_LIKE.fullmatch(title):
            continue
        if RE_SUFFIX_NOISE.search(title):
            continue
        titles[title] = None
    return list(titles.keys())


def static_filter(out: Dict[str, List[str]]) -> int:
    """이미 디스크에 저장된 분기 데이터에도 META_TOKENS / suffix 차단을 일괄 적용.
    fetch_titles에서만 거르면 증분 빌드 시 옛 데이터에 노이즈가 남으므로 보강용.
    반환: 제거한 토큰 수(분기 별 합산).
    """
    removed = 0
    for q in out:
        kept: "OrderedDict[str, None]" = OrderedDict()
        for t in out[q]:
            if t in META_TOKENS:
                removed += 1
                continue
            if t.startswith(TITLE_PREFIX_BLOCK):
                removed += 1
                continue
            if RE_SUFFIX_NOISE.search(t):
                removed += 1
                continue
            kept[t] = None
        out[q] = list(kept.keys())
    return removed


def frequency_filter(out: Dict[str, List[str]], threshold: float) -> int:
    """여러 분기에 걸쳐 공통 등장하는 토큰을 사이드바/푸터/슬롯 노이즈로 보고 일괄 제거.
    threshold: 0~1, 비율. 분기 N개 중 threshold*N 이상에 등장하면 차단.
    한 작품은 보통 1~4분기(4쿨작 한정)에만 등장하므로 0.2 이하면 작품을 잘라낼 위험.
    반환: 제거한 토큰 수.
    """
    from collections import Counter
    n = len([q for q in out.values() if q])
    if n < 2:
        return 0
    cnt: "Counter[str]" = Counter()
    for titles in out.values():
        for t in set(titles):
            cnt[t] += 1
    min_n = max(2, int(threshold * n))
    noise = {t for t, c in cnt.items() if c >= min_n}
    if not noise:
        return 0
    sample = sorted(noise)[:15]
    logger.info(
        f"Frequency filter: removing {len(noise)} tokens appearing in >= {min_n}/{n} quarters; "
        f"examples={sample}"
    )
    for q in out:
        out[q] = [t for t in out[q] if t not in noise]
    return len(noise)


def main() -> None:
    qs = quarters(START, END)
    logger.info(f"Building seed for {len(qs)} quarters: {qs[0]} ~ {qs[-1]} -> {OUTPUT}")

    # 기존 출력이 있으면 이어쓰기(증분 빌드 친화)
    out: Dict[str, List[str]] = {}
    if os.path.exists(OUTPUT):
        try:
            with open(OUTPUT, encoding='utf-8') as f:
                out = json.load(f) or {}
            logger.info(f"Resuming from existing {OUTPUT} ({len(out)} quarters loaded)")
        except Exception as e:
            logger.warning(f"Existing {OUTPUT} unreadable, starting fresh: {e}")
            out = {}

    driver = build_driver()
    try:
        for q in qs:
            if q in out and out[q]:
                logger.info(f"  {q}: skip ({len(out[q])} titles already)")
                continue
            y, m = q.split('-')
            try:
                titles = fetch_titles(driver, int(y), int(m))
                logger.info(f"  {q}: {len(titles)} titles")
                out[q] = titles
            except Exception as e:
                logger.error(f"  {q}: failed {e}")
                out[q] = out.get(q, [])
            with open(OUTPUT, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
    finally:
        driver.quit()

    static_removed = static_filter(out)
    if static_removed:
        logger.info(f"Static filter removed {static_removed} entries (META/prefix/suffix)")

    threshold = float(os.getenv("SEED_FREQ_THRESHOLD", "0.5"))
    removed = frequency_filter(out, threshold)
    if static_removed or removed:
        with open(OUTPUT, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        logger.info(f"Wrote {OUTPUT} (static={static_removed}, frequency={removed})")

    total = sum(len(v) for v in out.values())
    logger.info(f"Done. Total {total} titles across {len(out)} quarters -> {OUTPUT}")


if __name__ == "__main__":
    main()
