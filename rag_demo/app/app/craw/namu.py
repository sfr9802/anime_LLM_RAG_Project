import json
import time
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

MAX_PAGES = 70

def init_driver():
    options = Options()
    # options.add_argument("--headless=new")  # 필요시 켜기
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--ignore-certificate-errors")
    return webdriver.Chrome(options=options)

def get_true_next_button(driver):
    buttons = driver.find_elements(By.CSS_SELECTOR, "a.ajxp5MEC")
    if not buttons:
        return None
    for btn in reversed(buttons):
        if btn.text.strip() == "다음" and btn.is_displayed():
            return btn
    return None

def get_all_titles_from_paginated_list(start_url: str) -> list:
    driver = init_driver()
    driver.get(start_url)
    time.sleep(5)

    titles = set()
    page = 1

    while True:
        print(f"\n📄 [페이지 {page}] 제목 수집 중...")
        soup = BeautifulSoup(driver.page_source, "html.parser")

        new_titles = set()
        for a in soup.find_all("a", href=True):
            title = a.get_text().strip()
            if 3 < len(title) < 100 and ":" not in title and "/" not in title:
                if title not in titles:
                    new_titles.add(title)
                    titles.add(title)

        print(f"  ➕ 이번 페이지에서 수집된 제목: {len(new_titles)}개")
        print(f"  📦 누적 수집된 총 제목 수: {len(titles)}개")

        if page >= MAX_PAGES:
            print(f"\n🚫 페이지 제한({MAX_PAGES}페이지)에 도달하여 크롤링을 종료합니다.")
            break

        next_button = get_true_next_button(driver)
        if next_button:
            print(f"  ↪ 다음 페이지로 이동 중...")
            driver.execute_script("arguments[0].click();", next_button)
            page += 1
            time.sleep(5)
        else:
            print("\n✅ 더 이상 '다음' 버튼이 없어 크롤링을 종료합니다.")
            break

    driver.quit()
    return sorted(titles)

if __name__ == "__main__":
    url = "https://namu.wiki/w/%EB%B6%84%EB%A5%98:%EC%9D%BC%EB%B3%B8%20%EC%95%A0%EB%8B%88%EB%A9%94%EC%9D%B4%EC%85%98/%EB%AA%A9%EB%A1%9D"
    titles = get_all_titles_from_paginated_list(url)
    print(f"\n🎉 최종 수집된 애니메이션 제목 수: {len(titles)}개")

    with open("anime_titles_paginated.json", "w", encoding="utf-8") as f:
        json.dump(titles, f, ensure_ascii=False, indent=2)

    print("📁 저장 완료: anime_titles_paginated.json")
