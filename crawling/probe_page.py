"""namu.wiki 페이지가 봇 탐지/리캡차에 걸리는지 빠른 진단."""
import sys, time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from bs4 import BeautifulSoup as BS

DRIVER = r"D:/port/crawling/chromedriver.exe"
URL = sys.argv[1] if len(sys.argv) > 1 else "https://namu.wiki/w/%EC%9B%90%ED%94%BC%EC%8A%A4"
WAIT = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0

opts = Options()
opts.add_argument('--headless=new')
opts.add_argument('--no-sandbox')
opts.add_argument('--disable-dev-shm-usage')
opts.add_argument('--disable-blink-features=AutomationControlled')
opts.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36')
opts.add_argument('--lang=ko-KR')
opts.add_argument('--window-size=1280,900')
opts.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
opts.add_experimental_option('useAutomationExtension', False)

driver = webdriver.Chrome(service=Service(executable_path=DRIVER), options=opts)
driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
})
try:
    print(f"GET {URL}")
    driver.get(URL)
    time.sleep(WAIT)
    src = driver.page_source
    soup = BS(src, 'html.parser')
    text = soup.get_text(' ', strip=True)
    print(f"page_source bytes: {len(src)}")
    print(f"text bytes:        {len(text)}")
    print(f"contains reCAPTCHA literal: {'reCAPTCHA' in src or 'recaptcha' in src}")
    print(f"og:title: {soup.find('meta', property='og:title')}")

    # section link probe (extract_child_links 로직 모사)
    import re
    from urllib.parse import unquote
    seed = soup.find('meta', property='og:title')
    seed_text = seed['content'] if seed and seed.has_attr('content') else None
    keywords = ["등장인물", "줄거리", "설정", "회차", "방영", "평가"]
    section_hits = []
    for a in soup.find_all('a', href=True):
        href = a['href'].split('#')[0].split('?')[0]
        if not href.startswith('/w/'):
            continue
        raw = href[len('/w/'):]
        decoded = unquote(raw)
        if '/' not in decoded:
            continue
        parts = decoded.split('/')
        if len(parts) != 2:
            continue
        name, section = parts
        if section in keywords:
            section_hits.append((name, section))
    uniq = sorted(set(section_hits))
    print(f"[section probe] seed_meta='{seed_text}' total a-tags={len(soup.find_all('a',href=True))} section-link-hits={len(section_hits)} unique={len(uniq)}")
    for n, s in uniq[:20]:
        print(f"  {n} / {s}")

    # 분류(category) prefix probe — 3-A 검증용
    # /w/분류:X/Y 패턴에서 X(슬래시 앞 prefix)를 모음.
    cat_links = []
    cat_prefixes = set()
    for a in soup.find_all('a', href=True):
        href = a['href'].split('#')[0].split('?')[0]
        if not href.startswith('/w/'):
            continue
        path = unquote(href[len('/w/'):])
        if not path.startswith('분류:'):
            continue
        cat_links.append(path)
        body = path[len('분류:'):]
        if '/' in body:
            head = body.split('/', 1)[0].strip()
            if len(head) >= 2:
                cat_prefixes.add(head)
    print(f"\n[category probe] total category links={len(cat_links)} extractable prefixes={len(cat_prefixes)}")
    for p in sorted(cat_prefixes)[:20]:
        print(f"  prefix: {p}")
    print(f"  (sample category links, first 10)")
    for c in cat_links[:10]:
        print(f"    {c}")

    print("--- first 400 chars of text ---")
    print(text[:400])
finally:
    driver.quit()
