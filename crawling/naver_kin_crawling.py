from bs4 import BeautifulSoup as Soup
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import ActionChains
import pandas as pd

driver = webdriver.Chrome('chromedriver.exe')


"""
fuck_popup = driver.find_element_by_xpath('//*[@id="eventPopupLayer"]/div[1]/div[1]/a')
fuck_popup.click()

trash_qa = driver.find_element_by_xpath('//*[@id="main_content"]/div[2]/div[1]/div/div[1]/div[1]/ul/li[15]/a')
trash_qa.click()

"""

trash_qa_list = []
for i in range(20) :
    i = str(i)
    driver.get('https://kin.naver.com/qna/list.naver?dirId=20&queryTime=2022-03-29%2014%3A35%3A36&page='+i)
    soup=Soup(driver.page_source,'lxml')

    driver.implicitly_wait(time_to_wait=1)
    
    """
    trash_qa_page = driver.find_element_by_xpath('//*[@id="pagingArea0"]/a['+i+']')
    trash_qa_page.click()
    """

    tit_txt = soup.select("#au_board_list > tr > td.title > a")
    print(tit_txt)
    for n in tit_txt :
        trash_qa_list.append(n.text)

df = pd.DataFrame({"trash q&a" : trash_qa_list})
df.to_csv('kin_trash_qa.csv', sep=',', float_format='%.64f')