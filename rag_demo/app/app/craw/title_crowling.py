# pip install selenium webdriver-manager
import json
import logging
import time
import signal
import sys
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException
from webdriver_manager.chrome import ChromeDriverManager

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# 전역 데이터 저장
all_data = {}

# SIGINT 핸들러: 중간 저장 후 종료
def handle_sigint(signum, frame):
    logging.warning("SIGINT received, saving data and exiting...")
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        logging.info(f"✅ Partial data saved to {out_file}")
    except Exception as e:
        logging.error(f"Error saving data on SIGINT: {e}")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_sigint)

# 출력 파일명
out_file = "anime_quarters_2006_2025.json"


def init_driver(headless=True):
    opts = Options()
    if headless:
        opts.add_argument("--headless")
        opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.implicitly_wait(5)
    return driver


def crawl_page(year, month):
    key = f"{year}-{month:02d}"
    driver = init_driver(headless=True)
    try:
        url = f"https://namu.wiki/w/애니메이션/{year}년 {month}월"
        logging.info(f"[{key}] Navigating to {url}")
        driver.get(url)
        time.sleep(1)

        wanted = [
            "월요일","화요일","수요일","목요일","금요일","토요일","일요일",
            "변칙 편성","극장개봉"
        ]
        data = {}
        for sec in wanted:
            try:
                h = driver.find_element(
                    By.XPATH,
                    f"//h5[.//span[@id='{sec}']]"
                )
                logging.info(f"[{key}] Found section header '{sec}'")
            except Exception:
                logging.warning(f"[{key}] Section '{sec}' not found")
                data[sec] = []
                continue

            try:
                ul = h.find_element(
                    By.XPATH,
                    "following::ul[contains(@class,'cAMrzemB')][1]"
                )
                items = [li.text.strip() for li in ul.find_elements(By.TAG_NAME, "li") if li.text.strip()]
                logging.info(f"[{key}] Section '{sec}': found {len(items)} items")
            except Exception:
                logging.warning(f"[{key}] No items in section '{sec}'")
                items = []
            data[sec] = items

        return data
    finally:
        driver.quit()


def main():
    global all_data
    months = [1, 4, 7, 10]

    try:
        for year in range(2006, 2025):
            for month in months:
                if year == 2025 and month > 7:
                    break

                key = f"{year}-{month:02d}"
                for attempt in range(1, 3):
                    logging.info(f"=== Crawling {key} (Attempt {attempt}) ===")
                    try:
                        page_data = crawl_page(year, month)
                        all_data[key] = page_data
                        break
                    except WebDriverException as e:
                        logging.error(f"[{key}] WebDriver error on attempt {attempt}: {e}")
                        if attempt == 2:
                            all_data[key] = {}
                    except Exception as e:
                        logging.error(f"[{key}] Unexpected error: {e}", exc_info=True)
                        all_data[key] = {}
                        break
    except KeyboardInterrupt:
        # SIGINT handled separately
        pass
    finally:
        # 최종 저장
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        logging.info(f"✅ Saved data to {out_file}")


if __name__ == "__main__":
    main()
