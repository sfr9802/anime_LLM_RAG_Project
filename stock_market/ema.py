import numpy as np
import pandas as pd

import yfinance as yf


def ema(length : int, ticker : str, interval : str, start_date : str, end_date : str) :
    data = yf.download(tickers= ticker, interval = interval, start = start_date, end = end_date)
    
    len_index = len(data.index)
    sma_data = data['Close']
    sum = 0 
    for i in sma_data :
        sum = sum + i
        
    sma = sum / len_index

    c_price = data['Close']
    c_price = c_price[1:-1]
    
    k = 2/(length+1)
    ema_f = c_price[0]*k + sma*(1-k)
    ema_f_list = []
    cnt = 0
    for i in c_price :
        if cnt == 0 :
            ema = i*k + ema_f*(1-k)
        else :
            ema = i*k + ema*(1-k)
        cnt = cnt + 1
        ema_f_list.append(ema)
    cnt = 0
    return ema_f_list
