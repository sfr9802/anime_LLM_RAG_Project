from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import csv
import time

# 우회용 옵션 설정
options = Options()
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option("useAutomationExtension", False)
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")

driver = webdriver.Chrome(options=options)

# navigator.webdriver 조작
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

BASE_URL = "https://www.yna.co.kr/news/{}?site=navi_latest_depth01"
MAX_PAGES = 5
article_data = []

for page_num in range(2, 2 + MAX_PAGES):
    url = BASE_URL.format(page_num)
    print(f"[{page_num}] 페이지 접근 중: {url}")
    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.tit-news"))
        )
        link_elements = driver.find_elements(By.CSS_SELECTOR, "a.tit-news")
        print(f" → {len(link_elements)}건 기사 링크 발견")

        for elem in link_elements:
            href = elem.get_attribute("href")
            if not href or "/view/" not in href:
                continue

            driver.get(href)
            time.sleep(2)
            try:
                title = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "h1.tit"))
                ).text.strip()
                date = driver.find_element(By.CSS_SELECTOR, "span.update-time").text.strip()
                paragraphs = driver.find_elements(By.CSS_SELECTOR, "article#articleWrap p")
                content = "\n".join(p.text.strip() for p in paragraphs if p.text.strip())

                article_data.append({
                    "url": href,
                    "title": title,
                    "date": date,
                    "content": content
                })
            except Exception as e:
                print(f" [!] 본문 수집 실패: {href} - {e}")

    except Exception as e:
        print(f"[!] 페이지 오류: {url} - {type(e).__name__}: {e}")
        continue

driver.quit()

# CSV 저장
with open("yonhap_titnews_final.csv", "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["url", "title", "date", "content"])
    writer.writeheader()
    for row in article_data:
        writer.writerow(row)

print("[✓] yonhap_titnews_final.csv 저장 완료!")
