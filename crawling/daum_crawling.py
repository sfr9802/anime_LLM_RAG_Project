from email import header
from bs4 import BeautifulSoup as Soup
from selenium import webdriver
import pandas as pd

driver = webdriver.Chrome('chromedriver.exe')

def next_btn() :
    home_next_btn = driver.find_element_by_class_name('ico_pctop btn_page btn_next')
    home_next_btn.click()

def society():
    page = "1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20"
    page_list = page.split(",")

    header_list = []
    news_address = []
    newsinfo_list = []

    for i in page_list :
        driver.get("https://news.daum.net/breakingnews/society?page="+i+"")
        
        html = driver.page_source
        soup = Soup(html, 'html.parser')

        breaking_headers = soup.select("#mArticle > div.box_etc > ul > li > div > strong > a")
        news_info = soup.select("#mArticle > div.box_etc > ul > li > div > strong > span")
        
        for n in breaking_headers :
            adress = n.get("href")
            news_address.append(adress)
            header_list.append(n.text)

        for j in news_info :
            newsinfo_list.append(j.text)


    df_breaking_headers = pd.DataFrame({'head' : header_list})
    df_headers_info = pd.DataFrame({'press' : newsinfo_list})
    df_news_address = pd.DataFrame({'address' : news_address})
        

    df_news = pd.concat([df_breaking_headers, df_headers_info, df_news_address], axis = 1)
    df_news.to_csv('daum_society.csv', sep=',', float_format='%.64f')

    print(df_news)

society()