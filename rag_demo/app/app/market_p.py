from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from datetime import datetime
import csv
import time
import re

# 셀레니움 우회 설정
options = Options()
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")

driver = webdriver.Chrome(options=options)

driver.execute_cdp_cmd(
    "Page.addScriptToEvaluateOnNewDocument",
    {
        "source": """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        """
    }
)

def extract_date_from_url(url):
    match = re.search(r"AKR(\d{8})", url)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            return None
    return None

BASE_URL = "https://www.yna.co.kr/market-plus/all/{}"
MAX_PAGES = 20
article_data = []

for page_num in range(1, 1 + MAX_PAGES):
    url = BASE_URL.format(page_num)
    print(f"[{page_num}] 페이지 접근 중: {url}")
    try:
        driver.get(url)
        time.sleep(2)

        items = driver.find_elements(By.CSS_SELECTOR, "li[data-cid]")
        print(f" → {len(items)}개 기사 블럭 발견")

        for item in items:
            try:
                url = item.find_element(By.CSS_SELECTOR, "a.tit-news").get_attribute("href")
                title = item.find_element(By.CSS_SELECTOR, "a.tit-news").text.strip()
                summary = item.find_element(By.CSS_SELECTOR, "p.lead").text.strip()
                date = extract_date_from_url(url)

                article_data.append({
                    "url": url,
                    "title": title,
                    "summary": summary,
                    "date": date
                })
            except Exception as e:
                print("  [!] 일부 요소 수집 실패:", e)

    except Exception as e:
        print(f"[!] 페이지 오류: {url} - {type(e).__name__}: {e}")
        continue

driver.quit()

# CSV 저장
with open("yonhap_summary_with_date_market_plus.csv", "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["url", "title", "summary", "date"])
    writer.writeheader()
    for row in article_data:
        writer.writerow(row)

print("[✓] yonhap_summary_with_date.csv 저장 완료!")
