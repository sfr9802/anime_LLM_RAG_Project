import time
import csv
import random
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280x800")
    options.add_argument(f"user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/{random.randint(90,120)}.0")
    return webdriver.Chrome(options=options)

def fetch_article(url):
    try:
        driver = get_driver()
        driver.get(url)
        time.sleep(random.uniform(2.5, 4.0))  # 렌더링 대기

        content = driver.find_element(By.CSS_SELECTOR, "div[data-tiara-layer='article']").text
        title = driver.title
        driver.quit()

        print(f"[+] 성공: {url}")
        return {"url": url, "title": title, "content": content}

    except Exception as e:
        print(f"[!] 실패: {url} - {e}")
        return {"url": url, "title": "", "content": ""}

def save_to_csv(results, filename="news_content.csv"):
    with open(filename, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "title", "content"])
        if f.tell() == 0:
            writer.writeheader()
        for row in results:
            if row["content"]:
                writer.writerow(row)

if __name__ == "__main__":
    with open("headlines_to_crawl.txt", "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(fetch_article, urls))

    save_to_csv(results)
