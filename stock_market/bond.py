
import datetime
import QuantLib as ql
import pandas as pd
import numpy as np
import requests
import urllib3
import matplotlib.pyplot as plt
from bs4 import BeautifulSoup as Soup


s = requests.Session()

def GET_DATE():
    req = s.get("https://www.wsj.com/market-data/bonds?", verify=False, headers={"User-Agent": "Mozilla/5.0"})
    
    

    html = req.text
    soup = Soup(html, "html.parser")
    data1 =soup.select_one('span.WSJBase--card__timestamp--3F2HxyAE').text

    date = datetime.datetime.strptime(data1, "%m/%d/%y").date()
    
    return date

def GET_QUOTE(reference_date):
    tenors = ['01M', '03M', '06M', '01Y', '02Y', '03Y', '05Y', '07Y', '10Y', '30Y']

    maturities = []
    days = []
    prices = []
    coupons = []

    for i, tenor in enumerate(tenors):
        req = s.get("https://www.wsj.com/market-data/quotes/bond/BX/TMUBMUSD"+tenor+"?mod=md_home_overview_quote", verify=False, headers={"User-Agent": "Mozilla/5.0"})
        
        html = req.text
        soup = Soup(html, 'html.parser')

        if i <= 3:
            data_src =  soup.select_one("#price_quote_val").text
            price = data_src
            price = price.split('/')
            price2 = float(price[0])
            price3 = float(price[1])
            price = 1 + (price2 / price3)
            
        else :
            data_src = soup.select_one("#price_quote_val").text
            price = data_src
            price = price.split()
            price1 = float(price[0])
            price = price[1].split('/')
            price2 = float(price[0])
            price3 = float(price[1])
            price = price1 + (price2 / price3)

            
         #coupon
        data_src2 = soup.select('body > div > div > section > div > div > div > ul > li > div > span.data_data')
        
        coupon = data_src2[2].text
        if coupon != '' :
            coupon = float(coupon[:-1])
        else : 
            coupon = 0.0

        maturity = data_src2[3].text
        maturity = datetime.datetime.strptime(maturity, '%m/%d/%y').date()

        days.append((maturity - reference_date).days)
        prices.append(price)
        coupons.append(coupon)
        maturities.append(maturity)
        
    #create dataframe
    df = pd.DataFrame([maturities, days, prices, coupons]).transpose()
    headers = ['maturity', 'days', 'price', 'coupon']
    df.columns = headers
    df.set_index('maturity', inplace = True)

    return df

ref_date = GET_DATE()
quote = GET_QUOTE(ref_date)
print(quote)

def TREASURY_CURVE(date, quote) :

    #Divide Quotes
    tbill = quote[0:4]
    tbond = quote[4:]

    #Set evaluation date // 평가일
    eval_date = ql.Date(date.day, date.month, date.year)
    ql.Settings.instance().evaluationDate = eval_date

    #Set Market conventions //시장관행
    calender = ql.UnitedStates()
    convention = ql.ModifiedFollowing
    day_counter = ql.ActualActual()
    end_of_month = True
    fixing_days = 1
    face_amount = 100
    coupon_frequency = ql.Period(ql.Semiannual)

    #Counstruct Treasury Bill Helpers  //무이표채
    bill_helpers = [ql.DepositRateHelper(ql.QuoteHandle(ql.SimpleQuote(r/100.0)), ql.Period(m, ql.Days), fixing_days, calender, convention, end_of_month, day_counter) for r, m in zip(tbill['price'], tbill['days'])]

    #Construct Treasury Bond Helpers //이표채 

    bond_helpers = []

    for p, c, m in zip(tbond['price'], tbond['coupon'], tbond['days']) :
        
        termiantion_date = eval_date + ql.Period(m, ql.Days)

        schedule = ql.Schedule(eval_date, termiantion_date, coupon_frequency, calender, convention, convention, ql.DateGeneration.Backward, end_of_month)

        bond_helper = ql.FixedRateBondHelper(ql.QuoteHandle(ql.SimpleQuote(p)), fixing_days, face_amount, schedule, [c/100.0], day_counter, convention)

        bond_helpers.append(bond_helper)

    #bind Helpers
    rate_helper = bill_helpers + bond_helpers

    #Build Curve
    yc_linearzero = ql.PiecewiseLinearZero(eval_date, rate_helper, day_counter)

    return yc_linearzero

def DISCOUNT_FACTOR(date, curve) :
    date = ql.Date(date.day, date.month, date.year)
    return curve.discount(date)

def ZERO_RATE(date, curve) : #제로금리 추출
    date = ql.Date(date.day, date.month, date.year)
    day_counter = ql.ActualActual()
    compounding = ql.Compounded
    freq = ql.Continuous
    zero_rate = curve.zeroRate(date, day_counter, compounding, freq).rate()
    return zero_rate

ref_date = GET_DATE()
quote = GET_QUOTE(ref_date)
curve = TREASURY_CURVE(ref_date, quote)

quote['discount factor'] = np.nan
quote['zero rate'] = np.nan

for date in quote.index :
    quote.loc[date, 'discount factor'] = DISCOUNT_FACTOR(date, curve)
    quote.loc[date, 'zero rate'] = ZERO_RATE(date, curve)

print(quote[['discount factor', 'zero rate']])

plt.figure(figsize=(16, 8))
plt.plot(quote['zero rate'], 'b.-')
plt.title('Zero Curve', loc='center')
plt.xlabel('Maturity')
plt.ylabel('Zero Rate')

plt.figure(figsize=(16, 8))
plt.plot(quote['discount factor'], 'r.-')
plt.title('Discount Curve', loc='center')
plt.xlabel('Maturity')
plt.ylabel('Discount Factor')

plt.show()



