from bs4 import BeautifulSoup as Soup
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import ActionChains
import pandas as pd
import time
options = webdriver.ChromeOptions()
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)")
driver = webdriver.Chrome('chromedriver.exe', options=options)


driver.get('https://map.naver.com/v5/')
driver.implicitly_wait(time_to_wait=3)
driver.find_element_by_xpath('/html/body/app/layout/div[3]/div[2]/shrinkable-layout/div/app-base/search-input-box/div/div/div/input').send_keys('여의도 주유소\ue007')
driver.switch_to_window
time.sleep(2)

driver.switch_to.frame('searchIframe')
soup=Soup(driver.page_source,'lxml')


oilshop_address_list = []
oilshop_name_list = []
oilshop_price_list = []

oilshop_scroll = soup.select("span._2se7g")

for a in oilshop_scroll :
    print(a.text)
print(oilshop_scroll, len(oilshop_scroll))

for i in range(1, len(oilshop_scroll)) :
    i = str(i)
    print(i)
    driver.find_element_by_xpath('/html/body/div[3]/div/div[2]/div[1]/ul/li['+i+']/div[1]/div/a').click()

    time.sleep(2)
    driver.switch_to_default_content()
    driver.switch_to.frame('entryIframe')

    soup_entyif = Soup(driver.page_source, 'lxml')

    oilshop_info = soup_entyif.select("#app-root > div > div > div.place_detail_wrapper > div > div > div > div > div > div > table > tbody")
    oilshop_name = soup_entyif.select("#_title > span._3XamX")
    oilshop_address = soup_entyif.select('#app-root > div > div > div.place_detail_wrapper > div > div > div > div > ul > li._1M_Iz._1aj6- > div > a > span._2yqUQ')
    
    
    for n, j, k in zip(oilshop_address, oilshop_name, oilshop_info) :
        oilshop_address_list.append(n.text)
        oilshop_name_list.append(j.text)
        oilshop_price_list.append(k.text)
    driver.switch_to_default_content()
    driver.switch_to.frame('searchIframe')



print(oilshop_address_list, oilshop_name_list, oilshop_price_list)