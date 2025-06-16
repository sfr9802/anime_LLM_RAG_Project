from selenium import webdriver
from bs4 import BeautifulSoup
import time

driver = webdriver.Chrome()
driver.get("https://www.yna.co.kr/news/2?site=navi_latest_depth01")
time.sleep(3)
soup = BeautifulSoup(driver.page_source, "html.parser")
articles = soup.select("a.newslist_link")

for a in articles:
    print("https://www.yna.co.kr" + a['href'])

driver.quit()
