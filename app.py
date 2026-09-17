# app.py
import base64
import datetime
import json
import os
import sys
import time

# 1. 優先將當前目錄加入 Python 搜尋路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

import custom_indicator
import dynamic_subchart
import exp
import medium_long_term_wave

from data_fetcher import fetch_60min_kline, fetch_min_kline, get_realtime_dde
from dynamic_subchart import get_subchart_data, get_subchart_echarts_config
from risk_card import render_risk_card


# ---------------------------------------------------------
# 1. 頁面配置與樣式
# ---------------------------------------------------------
st.set_page_config(
    page_title="台股 & 台指期 K 線即時監控站",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown(
    """
    <style>
    .stock-info-card {
        background-color: #1E222D;
        padding: 12px;
        border-radius: 8px;
        border: 1px solid #2A2E39;
        margin-bottom: 12px;
    }
    .metric-title { font-size: 13px; color: #888888; font-weight: bold; margin-bottom: 6px; }
    .metric-row { display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; border-bottom: 1px dashed #2A2E39; }
    .metric-label { color: #CCCCCC; }
    .metric-value { font-weight: bold; color: #FFFFFF; }
    </style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# 2. 數據獲取與基準價計算
# ---------------------------------------------------------
@st.cache_data(ttl=3600)
def get_stock_name(stock_code):
    clean_code = str(stock_code).strip().upper().replace(".TW", "").replace(".TWO", "")
    special_names = {
        "TX": "台指期近全",
        "FITX": "台指期近全",
        "WTX": "台指期近全",
        "IX0001": "加權指數",
        "0000": "加權指數",
        "TAIEX": "加權指數"
    }
    if clean_code in special_names:
        return special_names[clean_code]

    url = "https://api.finmindtrade.com/api/v4/data"
    params = {"dataset": "TaiwanStockInfo"}
    try:
        res = requests.get(url, params=params, timeout=5)
        data = res.json()
        if data.get("msg") == "success":
            df_info = pd.DataFrame(data["data"])
            matched = df_info[df_info["stock_id"] == clean_code]
            if not matched.empty:
                return matched.iloc[0]["stock_name"]
    except Exception:
        pass
    return clean_code


@st.cache_data(ttl=3600)
def fetch_institutional_data(stock_code):
    """取得近 7 日三大法人買賣超資料（含帶容錯機制）"""
    clean_code = str(stock_code).strip().upper().replace(".TW", "").replace(".TWO", "")
    target_id = "TAIEX" if clean_code in ["IX0001", "0000", "TAIEX"] else clean_code
    
    end_date = datetime.date.today().strftime("%Y-%m-%d")
    start_date = (datetime.date.today() - datetime.timedelta(days=20)).strftime("%Y-%m-%d")
    
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": target_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    
    try:
        res = requests.get(url, params=params, timeout=5)
        data = res.json()
        if data.get("msg") == "success" and data.get("data"):
            df = pd.DataFrame(data["data"])
            df["buy_minus_sell"] = (df["buy"] - df["sell"]) / 1000
            
            pivoted = df.pivot_table(
                index="date", 
                columns="name", 
                values="buy_minus_sell", 
                aggfunc="sum"
            ).fillna(0)
            
            pivoted = pivoted.tail(7).reset_index()
            pivoted.rename(columns={"date": "日期"}, inplace=True)
            
            for col in ["Foreign_Investor", "Investment_Trust", "Dealer_Self"]:
                if col not in pivoted.columns:
                    pivoted[col] = 0
                    
            pivoted.rename(columns={
                "Foreign_Investor": "外資",
                "Investment_Trust": "投信",
                "Dealer_Self": "自營商"
            }, inplace=True)
            
            pivoted["外資"] = pivoted["外資"].astype(int)
            pivoted["投信"] = pivoted["投信"].astype(int)
            pivoted["自營商"] = pivoted["自營商"].astype(int)
            pivoted["合計"] = pivoted["外資"] + pivoted["投信"] + pivoted["自營商"]
            
            return pivoted[["日期", "外資", "投信", "自營商", "合計"]].sort_values("日期", ascending=False)
    except Exception:
        pass
        
    return pd.DataFrame(columns=["日期", "外資", "投信", "自營商", "合計"])


@st.cache_data
def fetch_stock_meta_and_kline(input_code):
    clean_code = str(input_code).strip().upper().replace(".TW", "").replace(".TWO", "")
    stock_name = get_stock_name(clean_code)

    end_date = datetime.date.today().strftime("%Y-%m-%d")
    start_date = (datetime.date.today() - datetime.timedelta(days=365 * 4)).strftime("%Y-%m-%d")

    url = "https://api.finmindtrade.com/api/v4/data"
    target_id = "TAIEX" if clean_code in ["IX0001", "0000", "TAIEX"] else clean_code

    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": target_id,
        "start_date": start_date,
        "end_date": end_date,
    }

    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()

        if data.get("msg") != "success" or not data.get("data"):
            return stock_name, clean_code, pd.DataFrame()

        df = pd.DataFrame(data["data"])
        df.rename(
            columns={
                "date": "DateStr",
                "open": "Open",
                "max": "High",
                "min": "Low",
                "close": "Close",
                "Trading_Volume": "Volume",
            },
            inplace=True,
        )

        df["Open"] = df["Open"].astype(float)
        df["High"] = df["High"].astype(float)
        df["Low"] = df["Low"].astype(float)
        df["Close"] = df["Close"].astype(float)
        df["Volume"] = (df["Volume"] / 1000).fillna(0).astype(int)

        return stock_name, clean_code, df

    except Exception as e:
        st.sidebar.error(f"日K資料讀取失敗: {e}")
        return stock_name, clean_code, pd.DataFrame()


def get_global_prev_close(df_daily, realtime):
    if isinstance(realtime, dict) and realtime.get("prev_close") and float(realtime["prev_close"]) > 0:
        return float(realtime["prev_close"])
    
    if not df_daily.empty and len(df_daily) >= 1:
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        last_date = str(df_daily.iloc[-1]["DateStr"])
        
        if last_date == today_str and len(df_daily) >= 2:
            return float(df_daily.iloc[-2]["Close"])
        else:
            return float(df_daily.iloc[-1]["Close"])
            
    return 0.0


def merge_realtime_to_daily(df_daily, realtime_data):
    if df_daily.empty or not realtime_data or not isinstance(realtime_data, dict):
        return df_daily

    df_res = df_daily.copy()
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    price = (
        realtime_data.get("price")
        or realtime_data.get("close")
        or realtime_data.get("last_price")
        or realtime_data.get("z")
    )
    if price is None:
        return df_res

    price = float(price)
    high = float(realtime_data.get("high") or price)
    low = float(realtime_data.get("low") or price)
    open_price = float(realtime_data.get("open") or price)
    volume = int(realtime_data.get("volume") or 0)

    last_date = str(df_res.iloc[-1]["DateStr"])

    if last_date == today_str:
        idx = df_res.index[-1]
        df_res.loc[idx, "High"] = max(df_res.loc[idx, "High"], high)
        df_res.loc[idx, "Low"] = min(df_res.loc[idx, "Low"], low)
        df_res.loc[idx, "Close"] = price
        if volume > 0:
            df_res.loc[idx, "Volume"] = volume
    else:
        new_row = {
            "DateStr": today_str,
            "Open": open_price,
            "High": high,
            "Low": low,
            "Close": price,
            "Volume": volume,
        }
        df_res = pd.concat([df_res, pd.DataFrame([new_row])], ignore_index=True)

    return df_res


def resample_kline(df_daily, timeframe="W"):
    if df_daily.empty:
        return df_daily

    df = df_daily.copy()
    df["Date"] = pd.to_datetime(df["DateStr"])
    df.set_index("Date", inplace=True)

    rule = "W-FRI" if timeframe == "W" else "ME"

    resampled = (
        df.resample(rule)
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna(subset=["Close"])
        .reset_index()
    )

    resampled["DateStr"] = resampled["Date"].dt.strftime("%Y-%m-%d")
    return resampled.drop(columns=["Date"])


# ---------------------------------------------------------
# 3. 技術指標計算
# ---------------------------------------------------------
def ema_func(series, period):
    return series.ewm(span=period, adjust=False, min_periods=0).mean()


def calculate_custom_indicators(df):
    if df.empty or len(df) < 5:
        return df

    df = df.copy()

    var1_fund = (df["Close"] - df["Close"].shift(1)) / df["Close"].shift(1) * 100
    var2_fund = (df["Close"] - df["Low"].rolling(9).min()) / (df["High"].rolling(9).max() - df["Low"].rolling(9).min()) * 100
    var3_fund = var2_fund.ewm(span=3, adjust=False).mean()
    var4_fund = var3_fund.ewm(span=3, adjust=False).mean()
    var5_fund = var4_fund.ewm(span=3, adjust=False).mean()
    df["資金爆發"] = np.where((var1_fund > 3) & (var5_fund < 80), var1_fund * 10, 0)

    gup6 = (2 * df["Close"] + df["High"] + df["Low"]) / 4
    gup7 = df["Low"].rolling(window=13, min_periods=1).min()
    gup8 = df["High"].rolling(window=13, min_periods=1).max()

    denom_gup = (gup8 - gup7).replace(0, np.nan)
    gup9_raw = (gup6 - gup7) / denom_gup * 100
    gup9 = gup9_raw.ewm(span=13, adjust=False).mean()

    weighted_gup9 = 0.382 * gup9.shift(2) + 0.618 * gup9
    df["波段拐點"] = (weighted_gup9.ewm(span=6, adjust=False).mean() - 50) / 100

    df["波段拐點_方向"] = np.where(
        df["波段拐點"] > df["波段拐點"].shift(1), 1,
        np.where(df["波段拐點"] < df["波段拐點"].shift(1), -1, 0)
    )

    llv60 = df["Low"].rolling(window=60, min_periods=1).min()
    hhv60 = df["High"].rolling(window=60, min_periods=1).max()

    denom_price = (hhv60 - llv60).replace(0, np.nan)
    gup_price = (df["Close"] - llv60) / denom_price

    ema_gup_price = gup_price.ewm(span=3, adjust=False).mean()
    gup1 = ema_gup_price.rolling(window=3, min_periods=1).mean()

    df["中期安全線"] = (gup1 - 0.5).ewm(span=55, adjust=False).mean()
    df["中期安全線_安全區"] = np.where(df["中期安全線"] > df["中期安全線"].shift(1), 1, 0)

    close = df["Close"]
    ema13_1 = ema_func(close, 13)
    vara = ema_func(ema13_1, 13)
    df["VARA"] = vara
    vara_prev = vara.shift(1)

    kp = (vara - vara_prev) / vara_prev * 1000
    df["KP"] = kp
    mm = kp.shift(1)
    df["MM"] = mm

    df["派"] = kp
    df["落"] = np.where(kp < 0, kp, np.nan)
    df["吸"] = np.where(kp >= mm, kp, np.nan)
    df["拉"] = np.where((kp >= 0) & (kp >= mm), kp, np.nan)

    df["JJ"] = (df["Close"] + df["High"] + df["Low"]) / 3
    df["E"] = df["JJ"].ewm(span=5, adjust=False).mean()
    df["D"] = df["E"].shift(1)
    df["E_gt_D"] = df["E"] > df["D"]

    df["工作線"] = df["Close"].ewm(span=5, adjust=False).mean()
    df["MA10"] = df["Close"].rolling(10, min_periods=1).mean()
    df["MA20"] = df["Close"].rolling(20, min_periods=1).mean()
    df["MA60"] = df["Close"].rolling(60, min_periods=1).mean()

    df["CROSS_GOLDEN"] = (df["工作線"] > df["MA20"]) & (df["工作線"].shift(1) <= df["MA20"].shift(1))

    ema8 = df["Close"].ewm(span=8, adjust=False).mean()
    ema13 = df["Close"].ewm(span=13, adjust=False).mean()
    df["DIF"] = ema8 - ema13
    df["MACD"] = df["DIF"].ewm(span=5, adjust=False).mean()
    df["MACD_Hist"] = (df["DIF"] - df["MACD"]) * 2

    zyg28 = df["Close"]
    zyg_sma1 = zyg28.ewm(alpha=1 / 2, adjust=False).mean()
    zyg_sma2 = zyg_sma1.ewm(alpha=1 / 2, adjust=False).mean()
    df["ZYG29"] = zyg_sma2.ewm(alpha=1 / 2, adjust=False).mean()
    df["ZYG30"] = df["ZYG29"].rolling(window=3, min_periods=1).mean()
    df["ZYG_Red"] = np.where(df["ZYG29"] > df["ZYG30"], df["ZYG29"], None)
    df["ZYG_Green"] = np.where(df["ZYG29"] <= df["ZYG30"], df["ZYG29"], None)

    df["ZYG_CROSS_BUY"] = (df["ZYG29"] > df["ZYG30"]) & (df["ZYG29"].shift(1) <= df["ZYG30"].shift(1))
    vol_ma5 = df["Volume"].rolling(window=5, min_periods=1).mean()
    df["V_UP"] = df["Volume"] > (vol_ma5 * 1.3)
    df["TREND_OK"] = df["Close"] > df["MA20"]
    df["REF_HHV10"] = df["High"].shift(1).rolling(window=10, min_periods=1).max()
    df["BREAK_BOX"] = df["Close"] > df["REF_HHV10"]

    df["HIGH_WIN_BUY"] = df["ZYG_CROSS_BUY"] & df["V_UP"] & df["TREND_OK"] & df["BREAK_BOX"]
    df["BASE_GD"] = df["ZYG_CROSS_BUY"] & (~df["HIGH_WIN_BUY"])
    df["SELL_ALL"] = (df["ZYG29"] <= df["ZYG30"]) & (df["ZYG29"].shift(1) > df["ZYG30"].shift(1))

    df["Signal_Text"] = None
    df["Signal_Color"] = None
    for i in range(len(df)):
        if df.iloc[i]["HIGH_WIN_BUY"]:
            df.iat[i, df.columns.get_loc("Signal_Text")] = "突破"
            df.iat[i, df.columns.get_loc("Signal_Color")] = "#FF00FF"
        elif df.iloc[i]["BASE_GD"]:
            df.iat[i, df.columns.get_loc("Signal_Text")] = "轉折"
            df.iat[i, df.columns.get_loc("Signal_Color")] = "#FFD700"

    df["主力啟動線"] = df["Volume"].rolling(5, min_periods=1).mean()
    df["主力洗盤線"] = df["Volume"].rolling(35, min_periods=1).mean()
    df["資金異動線"] = df["Volume"].rolling(120, min_periods=1).mean()

    cross_start_fund = (df["主力啟動線"] > df["資金異動線"]) & (df["主力啟動線"].shift(1) <= df["資金異動線"].shift(1))
    cross_start_wash = (df["主力啟動線"] > df["主力洗盤線"]) & (df["主力啟動線"].shift(1) <= df["主力洗盤線"].shift(1))
    df["VOL_出擊"] = cross_start_fund | ((df["主力洗盤線"] > df["資金異動線"]) & cross_start_wash)

    cross_vol_start = (df["Volume"] > df["主力啟動線"]) & (df["Volume"].shift(1) <= df["主力啟動線"].shift(1))
    ref_vol_low = (df["Volume"].shift(1) < df["資金異動線"].shift(1)) | (df["Volume"].shift(2) < df["資金異動線"].shift(2))
    df["VOL_啟動"] = (df["主力啟動線"] > df["主力啟動線"].shift(1)) & cross_vol_start & ref_vol_low

    df["V1"] = (df["Close"] / df["Close"].shift(3)) >= 1.10
    v1_forward = df["V1"].shift(-1).fillna(False)
    df["VOL_OK"] = df["V1"] | v1_forward

    var1_ema1 = df["Close"].ewm(span=9, adjust=False).mean()
    var1 = var1_ema1.ewm(span=9, adjust=False).mean()

    var1_ref1 = var1.shift(1)
    df["控盤"] = np.where(var1_ref1 != 0, (var1 - var1_ref1) / var1_ref1 * 1000, 0)
    df["控盤_REF"] = df["控盤"].shift(1)

    df["AA0"] = (df["控盤"] > 0) & (df["控盤_REF"] <= 0)
    df["開始控盤"] = np.where(df["AA0"], 5.0, 0.0)

    low_60 = df["Low"].rolling(window=60, min_periods=1).min()
    high_60 = df["High"].rolling(window=60, min_periods=1).max()
    price_range = np.where((high_60 - low_60) == 0, 1, high_60 - low_60)

    winner_95 = np.clip((df["Close"] * 0.95 - low_60) / price_range * 100, 0, 100)
    cost_85 = low_60 + price_range * 0.85

    df["無莊控盤"] = df["控盤"] < 0
    df["有莊控盤"] = (df["控盤"] > df["控盤_REF"]) & (df["控盤"] > 0)
    df["高度控盤"] = (winner_95 > 50) & (df["Close"] > cost_85) & (df["控盤"] > 0)
    df["主力出貨"] = (df["控盤"] < df["控盤_REF"]) & (df["控盤"] > 0)

    return df


# ---------------------------------------------------------
# 4. ECharts 圖表繪製
# ---------------------------------------------------------
def render_echarts_html(df, height=1050, sub1_metric="資金爆發"):
    dates = df["DateStr"].tolist()

    def clean_list(series):
        return [None if pd.isna(x) else round(float(x), 2) for x in series]

    six_y_axis_config = None

    if sub1_metric == "資金爆發":
        sub1_series = get_subchart_data(df, metric_name="主力資金")
    elif sub1_metric in ["波段拐點", "波段起爆點"]:
        sub1_series = exp.get_explosion_subchart_data(df)
    elif sub1_metric == "六脈神劍":
        df_six = custom_indicator.tdx_resonance_strategy(df)
        sub1_series = get_subchart_data(df_six, metric_name="六脈神劍")
        
        # 設定六脈神劍 Y 軸顯示 6 個指標名稱標籤
        six_indicators = [
            ("ABC1", 15, "MACD"),
            ("ABC2", 30, "KDJ"),
            ("ABC3", 45, "RSI"),
            ("ABC4", 60, "LWR"),
            ("ABC5", 75, "BBI"),
            ("ABC6", 90, "ZLMM"),
        ]
        six_y_axis_config = {
            "scale": True,
            "gridIndex": 1,
            "min": 0,
            "max": 100,
            "interval": 15,
            "axisLabel": {
                "show": True,
                "color": "#CCCCCC",
                "fontSize": 10,
                "formatter": "function(value) {"
                             "  var map = {15:'MACD', 30:'KDJ', 45:'RSI', 60:'LWR', 75:'BBI', 90:'ZLMM'};"
                             "  return map[value] || '';"
                             "}"
            },
            "splitLine": {"show": True, "lineStyle": {"color": "#2A2E39"}},
        }
    elif sub1_metric == "中長期波段":
        df_wave = medium_long_term_wave.get_medium_long_term_wave_data(df)
        def make_continuous_direction_line(values, mask, other_mask=None):
            values = np.asarray(values, dtype=float)
            mask = pd.Series(mask).fillna(False).to_numpy(dtype=bool)
            out = np.full(len(values), np.nan, dtype=float)
            out[mask] = values[mask]

            if other_mask is not None:
                other_mask = pd.Series(other_mask).fillna(False).to_numpy(dtype=bool)
                for j in range(1, len(out)):
                    if (not mask[j]) and mask[j - 1] and other_mask[j]:
                        out[j] = values[j]

            return out

        long_up_data = make_continuous_direction_line(df_wave["長期波動"], df_wave["長期方向上升"], df_wave["長期方向下降"])
        long_down_data = make_continuous_direction_line(df_wave["長期波動"], df_wave["長期方向下降"], df_wave["長期方向上升"])
        medium_up_data = make_continuous_direction_line(df_wave["中期波動"], df_wave["中級方向上升"], df_wave["中級方向下降"])
        medium_down_data = make_continuous_direction_line(df_wave["中期波動"], df_wave["中級方向下降"], df_wave["中級方向上升"])

        hzs_points, lzs_points = [], []
        for i, row in df_wave.iterrows():
            date_str = str(row["DateStr"])
            if bool(row.get("HZS", False)):
                hzs_points.append({
                    "name": "HZS", "coord": [date_str, float(row["長期波動"])], "value": "買入",
                    "symbol": "arrow", "symbolSize": 10, "itemStyle": {"color": "#FF3333"},
                    "label": {"position": "bottom", "color": "#FF3333", "fontSize": 10},
                })
            if bool(row.get("LZS", False)):
                lzs_points.append({
                    "name": "LZS", "coord": [date_str, float(row["長期波動"])], "value": "賣出",
                    "symbol": "arrow", "symbolSize": 10, "symbolRotate": 180, "itemStyle": {"color": "#00CC66"},
                    "label": {"position": "top", "color": "#00CC66", "fontSize": 10},
                })

        sub1_series = [
            {"name": "長期方向上升", "type": "line", "data": clean_list(long_up_data), "xAxisIndex": 1, "yAxisIndex": 1, "showSymbol": False, "connectNulls": False, "lineStyle": {"color": "#FF3333", "width": 4}, "markPoint": {"data": hzs_points}},
            {"name": "長期方向下降", "type": "line", "data": clean_list(long_down_data), "xAxisIndex": 1, "yAxisIndex": 1, "showSymbol": False, "connectNulls": False, "lineStyle": {"color": "#00CC66", "width": 4}, "markPoint": {"data": lzs_points}},
            {"name": "中級方向上升", "type": "line", "data": clean_list(medium_up_data), "xAxisIndex": 1, "yAxisIndex": 1, "showSymbol": False, "connectNulls": False, "lineStyle": {"color": "#FF6666", "width": 2}},
            {"name": "中級方向下降", "type": "line", "data": clean_list(medium_down_data), "xAxisIndex": 1, "yAxisIndex": 1, "showSymbol": False, "connectNulls": False, "lineStyle": {"color": "#00AA55", "width": 2}},
        ]
    else:
        sub1_series = get_subchart_data(df, sub1_metric)

    k_values = []
    for _, row in df.iterrows():
        open_val, close_val = float(row["Open"]), float(row["Close"])
        low_val, high_val = float(row["Low"]), float(row["High"])

        if row.get("CROSS_GOLDEN", False):
            k_values.append({
                "value": [open_val, close_val, low_val, high_val],
                "itemStyle": {"color": "#FFFFFF", "color0": "#FFFFFF", "borderColor": "#FFFFFF", "borderColor0": "#FFFFFF"},
            })
        else:
            k_values.append([open_val, close_val, low_val, high_val])

    yellow_bar_data = []
    for _, row in df.iterrows():
        if row.get("E_gt_D", False) and pd.notna(row.get("D")):
            d_val = round(float(row["D"]), 2)
            e_val = round(float(row["E"]), 2)
            yellow_bar_data.append([d_val, e_val, d_val, e_val])
        else:
            yellow_bar_data.append([None, None, None, None])

    mark_points = []
    for idx, row in df.iterrows():
        if pd.notna(row.get("Signal_Text")):
            mark_points.append({
                "name": str(row["Signal_Text"]),
                "coord": [str(row["DateStr"]), float(row["Low"])],
                "value": str(row["Signal_Text"]),
                "symbol": "arrow", "symbolSize": 8,
                "itemStyle": {"color": str(row["Signal_Color"])},
                "label": {"position": "bottom", "distance": 5, "fontSize": 11, "color": str(row["Signal_Color"])},
            })
        if row.get("SELL_ALL", False):
            mark_points.append({
                "name": "賣點",
                "coord": [str(row["DateStr"]), float(row["High"])],
                "value": "賣點",
                "symbol": "arrow", "symbolSize": 8, "symbolRotate": 180,
                "itemStyle": {"color": "#00FF00"},
                "label": {"position": "top", "distance": 5, "fontSize": 11, "color": "#00FF00"},
            })

    vol_base_data, vol_white_line_data = [], []
    for _, row in df.iterrows():
        vol_val = int(row["Volume"])
        if row.get("VOL_OK", False): color = "#FF0033"
        elif row.get("VOL_出擊", False): color = "#FFFF00"
        elif row.get("VOL_啟動", False): color = "#00FF00"
        else: color = "#CC2222" if row["Close"] >= row["Open"] else "#00AA00"

        vol_base_data.append({"value": vol_val, "itemStyle": {"color": color}})
        vol_white_line_data.append(vol_val if row.get("VOL_OK", False) else None)

    macd_data = [
        {
            "value": round(float(row["MACD_Hist"]), 2),
            "itemStyle": {"color": "#FF3333" if row["MACD_Hist"] >= 0 else "#00AA00"},
        }
        for _, row in df.iterrows()
    ]

    zhuang_data, kaishi_line_data = [], []
    for idx, row in df.iterrows():
        val = round(float(row["控盤"]), 2) if pd.notna(row.get("控盤")) else 0
        color = "#FF00FF" if row.get("高度控盤", False) else ("#FF3333" if row.get("有莊控盤", False) else ("#00FF00" if row.get("主力出貨", False) else "#FFFFFF"))
        zhuang_data.append({"value": val, "itemStyle": {"color": color}})
        kaishi_line_data.append(5.0 if row.get("AA0", False) else 0.0)

    total_len = len(dates)
    start_percent = max(0, int((1 - 70 / total_len) * 100)) if total_len > 70 else 0

    series_list = [
        {"name": "黃色多頭帶", "type": "candlestick", "data": yellow_bar_data, "xAxisIndex": 0, "yAxisIndex": 0, "z": 1, "itemStyle": {"color": "#FFFF00", "color0": "#FFFF00", "borderColor": "#FFFF00", "borderColor0": "#FFFF00"}},
        {"name": "K線", "type": "candlestick", "data": k_values, "xAxisIndex": 0, "yAxisIndex": 0, "z": 2, "itemStyle": {"color": "#FF3333", "color0": "#00AA00", "borderColor": "#FF3333", "borderColor0": "#00AA00"}, "markPoint": {"data": mark_points}},
        {"name": "EMA5", "type": "line", "data": clean_list(df["工作線"]), "xAxisIndex": 0, "yAxisIndex": 0, "showSymbol": False, "lineStyle": {"color": "#FFFFFF", "width": 1}},
        {"name": "MA10", "type": "line", "data": clean_list(df["MA10"]), "xAxisIndex": 0, "yAxisIndex": 0, "showSymbol": False, "lineStyle": {"color": "#FFFF00", "width": 1}},
        {"name": "MA20", "type": "line", "data": clean_list(df["MA20"]), "xAxisIndex": 0, "yAxisIndex": 0, "showSymbol": False, "lineStyle": {"color": "#FF1493", "width": 1}},
        {"name": "MA60", "type": "line", "data": clean_list(df["MA60"]), "xAxisIndex": 0, "yAxisIndex": 0, "showSymbol": False, "lineStyle": {"color": "#00FFFF", "width": 1}},
        {"name": "趨勢紅線", "type": "line", "data": clean_list(df["ZYG_Red"]), "xAxisIndex": 0, "yAxisIndex": 0, "showSymbol": False, "lineStyle": {"color": "#FF0055", "width": 3}},
        {"name": "趨勢綠線", "type": "line", "data": clean_list(df["ZYG_Green"]), "xAxisIndex": 0, "yAxisIndex": 0, "showSymbol": False, "lineStyle": {"color": "#00FF66", "width": 3}},
    ]

    series_list.extend(sub1_series)
    series_list.extend([
        {"name": "成交量", "type": "bar", "data": vol_base_data, "xAxisIndex": 2, "yAxisIndex": 2},
        {"name": "OK白線", "type": "bar", "data": vol_white_line_data, "xAxisIndex": 2, "yAxisIndex": 2, "barWidth": 6, "barGap": "-100%", "z": 10, "itemStyle": {"color": "#FFFFFF"}},
        {"name": "主力啟動線(5)", "type": "line", "data": clean_list(df["主力啟動線"]), "xAxisIndex": 2, "yAxisIndex": 2, "showSymbol": False, "lineStyle": {"color": "#FFFFFF", "width": 1}},
        {"name": "主力洗盤線(35)", "type": "line", "data": clean_list(df["主力洗盤線"]), "xAxisIndex": 2, "yAxisIndex": 2, "showSymbol": False, "lineStyle": {"color": "#FFFF00", "width": 1}},
        {"name": "資金異動線(120)", "type": "line", "data": clean_list(df["資金異動線"]), "xAxisIndex": 2, "yAxisIndex": 2, "showSymbol": False, "lineStyle": {"color": "#00FF00", "width": 1}},
        {"name": "MACD", "type": "bar", "data": macd_data, "xAxisIndex": 3, "yAxisIndex": 3},
        {"name": "DIF", "type": "line", "data": clean_list(df["DIF"]), "xAxisIndex": 3, "yAxisIndex": 3, "showSymbol": False, "lineStyle": {"color": "#FFFFFF", "width": 1}},
        {"name": "DEA", "type": "line", "data": clean_list(df["MACD"]), "xAxisIndex": 3, "yAxisIndex": 3, "showSymbol": False, "lineStyle": {"color": "#FFFF00", "width": 1}},
        {"name": "莊家控盤", "type": "bar", "data": zhuang_data, "xAxisIndex": 4, "yAxisIndex": 4},
        {"name": "開始控盤", "type": "line", "data": kaishi_line_data, "xAxisIndex": 4, "yAxisIndex": 4, "showSymbol": False, "lineStyle": {"color": "#FFFF00", "width": 2}},
        {"name": "MM", "type": "line", "data": clean_list(df["MM"]), "xAxisIndex": 5, "yAxisIndex": 5, "showSymbol": False, "lineStyle": {"color": "#888888", "width": 1, "type": "dashed"}},
        {"name": "派", "type": "line", "data": clean_list(df["派"]), "xAxisIndex": 5, "yAxisIndex": 5, "showSymbol": False, "lineStyle": {"color": "#00FF00", "width": 2}},
        {"name": "落", "type": "line", "data": clean_list(df["落"]), "xAxisIndex": 5, "yAxisIndex": 5, "showSymbol": False, "lineStyle": {"color": "#FFFFFF", "width": 2}},
        {"name": "吸", "type": "line", "data": clean_list(df["吸"]), "xAxisIndex": 5, "yAxisIndex": 5, "showSymbol": False, "lineStyle": {"color": "#F08080", "width": 2}},
        {"name": "拉", "type": "line", "data": clean_list(df["拉"]), "xAxisIndex": 5, "yAxisIndex": 5, "showSymbol": False, "lineStyle": {"color": "#FF0000", "width": 2}},
    ])

    sub1_y_axis = six_y_axis_config if six_y_axis_config else {"scale": True, "gridIndex": 1, "splitLine": {"show": True, "lineStyle": {"color": "#2A2E39"}}}

    options = {
        "backgroundColor": "#131722",
        "animation": False,
        "tooltip": {"show": True, "trigger": "axis"},
        "grid": [
            {"left": "4%", "right": "3%", "top": "2%", "height": "30%"},
            {"left": "4%", "right": "3%", "top": "34%", "height": "10%"},
            {"left": "4%", "right": "3%", "top": "46%", "height": "10%"},
            {"left": "4%", "right": "3%", "top": "58%", "height": "10%"},
            {"left": "4%", "right": "3%", "top": "70%", "height": "10%"},
            {"left": "4%", "right": "3%", "top": "82%", "height": "10%"},
        ],
        "xAxis": [
            {"type": "category", "data": dates, "gridIndex": 0},
            {"type": "category", "data": dates, "gridIndex": 1, "axisLabel": {"show": False}},
            {"type": "category", "data": dates, "gridIndex": 2, "axisLabel": {"show": False}},
            {"type": "category", "data": dates, "gridIndex": 3, "axisLabel": {"show": False}},
            {"type": "category", "data": dates, "gridIndex": 4, "axisLabel": {"show": False}},
            {"type": "category", "data": dates, "gridIndex": 5, "axisLabel": {"show": False}},
        ],
        "yAxis": [
            {"scale": True, "gridIndex": 0},
            sub1_y_axis,
            {"scale": True, "gridIndex": 2},
            {"scale": True, "gridIndex": 3},
            {"scale": True, "gridIndex": 4, "splitLine": {"show": True, "lineStyle": {"color": "#2A2E39"}}},
            {"scale": True, "gridIndex": 5, "splitLine": {"show": True, "lineStyle": {"color": "#2A2E39"}}},
        ],
        "dataZoom": [
            {"type": "inside", "xAxisIndex": [0, 1, 2, 3, 4, 5], "start": start_percent, "end": 100},
            {"type": "slider", "xAxisIndex": [0, 1, 2, 3, 4, 5], "start": start_percent, "end": 100, "bottom": "1%"},
        ],
        "series": series_list,
    }

    options_json = json.dumps(options)
    
    # 針對含有 JS function 標籤做替換，以確保 JS 能正確執行
    options_json = options_json.replace(
        '"formatter": "function(value) {  var map = {15:\'MACD\', 30:\'KDJ\', 45:\'RSI\', 60:\'LWR\', 75:\'BBI\', 90:\'ZLMM\'};  return map[value] || \'\';}"',
        '"formatter": function(value) { var map = {15:\'MACD\', 30:\'KDJ\', 45:\'RSI\', 60:\'LWR\', 75:\'BBI\', 90:\'ZLMM\'}; return map[value] || \'\'; }'
    )

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
        <style>
            html, body {{ margin: 0; padding: 0; width: 100%; height: 100%; background-color: #131722; }}
            #main {{ width: 100%; height: {height}px; }}
        </style>
    </head>
    <body>
        <div id="main"></div>
        <script type="text/javascript">
            var chartDom = document.getElementById('main');
            var myChart = echarts.init(chartDom, 'dark');
            var option = {options_json};
            myChart.setOption(option);
            window.addEventListener('resize', function() {{ myChart.resize(); }});
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=height + 10)


# ---------------------------------------------------------
# 5. 主畫面與側邊欄數據綁定
# ---------------------------------------------------------
st.sidebar.title("📈 台股 & 台指期 監控站")

st.sidebar.markdown("**快捷代碼選擇：**")
quick_cols = st.sidebar.columns(3)
if quick_cols[0].button("加權指數"):
    st.session_state["stock_search_input"] = "IX0001"
if quick_cols[1].button("台指期近全"):
    st.session_state["stock_search_input"] = "FITX"
if quick_cols[2].button("台積電"):
    st.session_state["stock_search_input"] = "2330"

col_search, col_btn = st.sidebar.columns([3, 1])
with col_search:
    stock_code = st.text_input("輸入代碼 (例如: IX0001/FITX/2330)", value="IX0001", key="stock_search_input")
with col_btn:
    st.write("")
    st.write("")
    submit_button = st.button("查詢")

input_code = stock_code.strip() if stock_code.strip() else "IX0001"

kline_type = st.sidebar.radio(
    "K線週期", 
    ["5分K", "15分K", "30分K", "60分K", "日K", "週K", "月K"], 
    horizontal=True, 
    key="kline_type"
)

st.sidebar.markdown("---")
auto_refresh = st.sidebar.checkbox("⚡ 開啟自動即時刷新", value=False)
refresh_interval = st.sidebar.slider("刷新間隔 (秒)", min_value=3, max_value=60, value=10, step=1)

if auto_refresh:
    js_code = f"""
        <script>
            setTimeout(function() {{ window.parent.location.reload(); }}, {refresh_interval * 1000});
        </script>
    """
    components.html(js_code, height=0)

sub1_metric = st.sidebar.selectbox(
    "副圖 1 指標切換",
    ["波段拐點", "資金爆發", "六脈神劍", "中長期波段"],
    key="sub1_metric_select"
)

if input_code:
    # 獲取基礎日K與即時API數據
    stock_name, clean_code, df_daily_raw = fetch_stock_meta_and_kline(input_code)
    
    try:
        realtime = get_realtime_dde(clean_code)
    except Exception:
        realtime = {}

    if not df_daily_raw.empty:
        df_daily_raw = (
            df_daily_raw.sort_values("DateStr")
            .drop_duplicates("DateStr", keep="last")
            .reset_index(drop=True)
        )
        df_daily_raw = merge_realtime_to_daily(df_daily_raw, realtime)

    # 決定 K 線週期數據
    if kline_type in ["5分K", "15分K", "30分K", "60分K"]:
        minutes_map = {"5分K": 5, "15分K": 15, "30分K": 30, "60分K": 60}
        selected_min = minutes_map[kline_type]
        
        try:
            if selected_min == 60:
                df_sub = fetch_60min_kline(clean_code)
            else:
                df_sub = fetch_min_kline(clean_code, timeframe=selected_min)
        except Exception:
            df_sub = pd.DataFrame()

        if not df_sub.empty:
            df_sub = (
                df_sub.sort_values("DateStr")
                .drop_duplicates("DateStr", keep="last")
                .reset_index(drop=True)
            )
            df = calculate_custom_indicators(df_sub)
        else:
            df = pd.DataFrame()
    elif kline_type == "日K":
        df = calculate_custom_indicators(df_daily_raw)
    elif kline_type == "週K":
        df_week = resample_kline(df_daily_raw, timeframe="W")
        df = calculate_custom_indicators(df_week)
    elif kline_type == "月K":
        df_month = resample_kline(df_daily_raw, timeframe="M")
        df = calculate_custom_indicators(df_month)

    # 全天基準昨收價
    global_prev_close = get_global_prev_close(df_daily_raw, realtime)

    # 【左側區塊 1】：即時行情診斷卡
    if not df.empty:
        latest_price = float(df.iloc[-1]["Close"])
        rt_price = float(realtime.get("price")) if (isinstance(realtime, dict) and realtime.get("price")) else latest_price
        rt_prev = global_prev_close if global_prev_close > 0 else rt_price

        rt_change = rt_price - rt_prev
        rt_pct = (rt_change / rt_prev * 100) if rt_prev > 0 else 0.0

        rt_color = "#FF3333" if rt_change > 0 else ("#00FF66" if rt_change < 0 else "#CCCCCC")
        rt_arrow = "▲" if rt_change > 0 else ("▼" if rt_change < 0 else "")

        diag_card_html = f"""
        <div class="stock-info-card">
            <div class="metric-title">🔍 即時行情診斷 ({datetime.datetime.now().strftime('%H:%M:%S')})</div>
            <div style="font-size: 13px; color: #9B9B9B;">{stock_name} ({clean_code})</div>
            <div style="font-size: 24px; font-weight: bold; color: {rt_color}; margin: 2px 0;">{rt_price:,.2f}</div>
            <div style="font-size: 14px; font-weight: 600; color: {rt_color}; margin-bottom: 8px;">{rt_arrow} {rt_change:+.2f} ({rt_pct:+.2f}%)</div>
            <div style="border-top: 1px solid #2A2E39; padding-top: 6px; font-size: 12px; display: grid; grid-template-columns: 1fr 1fr; row-gap: 4px; color: #D1D4DC;">
                <div><span style="color: #9B9B9B;">開盤：</span><span style="color: #FFFFFF; font-weight: 600;">{float(realtime.get('open', df.iloc[-1]['Open'])):,.2f}</span></div>
                <div><span style="color: #9B9B9B;">最高：</span><span style="color: #FFFFFF; font-weight: 600;">{float(realtime.get('high', df.iloc[-1]['High'])):,.2f}</span></div>
                <div><span style="color: #9B9B9B;">最低：</span><span style="color: #FFFFFF; font-weight: 600;">{float(realtime.get('low', df.iloc[-1]['Low'])):,.2f}</span></div>
                <div><span style="color: #9B9B9B;">昨收：</span><span style="color: #FFFFFF; font-weight: 600;">{rt_prev:,.2f}</span></div>
            </div>
        </div>
        """
        st.sidebar.markdown(diag_card_html, unsafe_allow_html=True)

    # 載入法人資料表
    df_inst = fetch_institutional_data(clean_code)
    table_rows = ""
    for _, row in df_inst.iterrows():
        table_rows += "<tr style='border-bottom: 1px solid #2A2E39;'>"
        table_rows += f"<td style='padding: 6px 2px; color: #CCCCCC;'>{row['日期']}</td>"
        for col in ["外資", "投信", "自營商", "合計"]:
            val = row[col]
            color = "#FF3333" if val > 0 else ("#00FF66" if val < 0 else "#888888")
            val_str = f"+{val}" if val > 0 else str(val)
            weight = "bold" if col == "合計" else "normal"
            table_rows += f"<td style='padding: 6px 2px; text-align: right; color: {color}; font-weight: {weight};'>{val_str}</td>"
        table_rows += "</tr>"

    if not df.empty and len(df) >= 5:
        latest = df.iloc[-1]

        bull_c1 = latest["Close"] > latest.get("工作線", latest["Close"])
        bull_c2 = (latest.get("ZYG29", 0) > latest.get("ZYG30", 0)) or latest.get("HIGH_WIN_BUY", False)
        bull_c3 = (latest.get("MACD_Hist", 0) > 0) or (latest.get("DIF", 0) > latest.get("MACD", 0))
        bull_c4 = (latest.get("控盤", 0) > 0) or (latest.get("控盤", 0) > latest.get("控盤_REF", 0))
        bull_c5 = pd.notna(latest.get("KP", 0)) and (latest.get("KP", 0) >= 0)
        bull_score = sum([bull_c1, bull_c2, bull_c3, bull_c4, bull_c5])

        bear_c1 = latest["Close"] < latest.get("MA10", latest["Close"])
        bear_c2 = (latest.get("ZYG29", 0) <= latest.get("ZYG30", 0)) or latest.get("SELL_ALL", False)
        bear_c3 = latest.get("DIF", 0) < latest.get("MACD", 0)
        bear_c4 = latest.get("控盤", 0) < 0
        bear_c5 = pd.notna(latest.get("KP", 0)) and (latest.get("KP", 0) < 0)
        bear_score = sum([bear_c1, bear_c2, bear_c3, bear_c5])

        if bull_score == 5:
            light_html = "<span style='color: #FF3333; font-size: 15px;'>🔴 <b>【紅燈：準備數錢 / 買進】</b></span>"
            box_border = "#FF3333"
        elif bull_score == 4:
            light_html = "<span style='color: #FF66B2; font-size: 15px;'>🟠 <b>【粉燈：多頭看漲 / 準備】</b></span>"
            box_border = "#FF66B2"
        elif bear_score == 5:
            light_html = "<span style='color: #00FF66; font-size: 15px;'>🟢 <b>【綠燈：賣點確立 / 閃人】</b></span>"
            box_border = "#00FF66"
        elif bear_score == 4:
            light_html = "<span style='color: #FFFF00; font-size: 15px;'>🟡 <b>【黃燈：逐步下跌 / 警戒】</b></span>"
            box_border = "#FFFF00"
        else:
            light_html = "<span style='color: #AAAAAA; font-size: 14px;'>⚪ <b>【灰燈：安靜抱股 / 觀望】</b></span>"
            box_border = "#2A2E39"

        st.sidebar.markdown(
            f"""
                <div class="stock-info-card" style="border: 2px solid {box_border}; text-align: center; padding: 10px; margin-bottom: 10px;">
                    <div class="metric-title">🚦 戰情多空共振燈號 ({kline_type})</div>
                    <div style="padding: 4px 0;">{light_html}</div>
                </div>
            """,
            unsafe_allow_html=True,
        )

        # 【左側區塊 2】：莊家抬轎與控盤狀態卡
        no_zhuang = "是" if latest.get("無莊控盤") else "否"
        has_zhuang = "是" if latest.get("有莊控盤") else "否"
        high_zhuang = "是" if latest.get("高度控盤") else "否"
        ship_zhuang = "是" if latest.get("主力出貨") else "否"

        if latest.get("高度控盤"):
            zhuang_summary = "<span style='color: #FF00FF; font-weight: bold;'>高度控盤 (主力鎖碼)</span>"
        elif latest.get("主力出貨"):
            zhuang_summary = "<span style='color: #00FF66; font-weight: bold;'>主力出貨 (減碼警戒)</span>"
        elif latest.get("有莊控盤"):
            zhuang_summary = "<span style='color: #FF3333; font-weight: bold;'>有莊控盤 (主力進場)</span>"
        else:
            zhuang_summary = "<span style='color: #888888;'>無莊控盤 (散戶游資)</span>"

        zhuang_card_html = f"""
        <div class="stock-info-card">
            <div class="metric-title">🏛️ 莊家抬轎狀態診斷</div>
            <div style="margin-bottom: 8px; font-size: 13px;">
                <span style="color: #9B9B9B;">目前狀態：</span><span style="color: #FFFFFF; font-weight: 600;">{zhuang_summary}</span>
            </div>
            <div class="metric-row"><span class="metric-label">無莊控盤</span><span class="metric-value">{no_zhuang}</span></div>
            <div class="metric-row"><span class="metric-label">有莊控盤</span><span class="metric-value" style="color: #FF3333;">{has_zhuang}</span></div>
            <div class="metric-row"><span class="metric-label">高度控盤</span><span class="metric-value" style="color: #FF00FF;">{high_zhuang}</span></div>
            <div class="metric-row"><span class="metric-label">主力出貨</span><span class="metric-value" style="color: #00FF66;">{ship_zhuang}</span></div>
        </div>
        """
        st.sidebar.markdown(zhuang_card_html, unsafe_allow_html=True)

        # 【左側區塊 3】：主力控盤與多空趨勢狀態卡
        kp_val = latest.get("KP", 0)
        mm_val = latest.get("MM", 0)
        kp_status = "拉升" if (kp_val >= 0 and kp_val >= mm_val) else ("吸籌" if kp_val >= mm_val else ("落體" if kp_val < 0 else "派發"))
        
        control_status = "高度控盤" if latest.get("高度控盤") else ("有莊控盤" if latest.get("有莊控盤") else ("主力出貨" if latest.get("主力出貨") else "無莊控盤"))
        zyg_status = "多頭攻擊" if (latest.get("ZYG29", 0) > latest.get("ZYG30", 0)) else "空頭防守"

        # 1. 計算多空動態顏色
        c_control = "#FF4D4D" if "有莊" in str(control_status) or "主力" in str(control_status) else "#FFFFFF"

        c_zyg = "#FF4D4D" if any(k in str(zyg_status) for k in ["多頭", "攻擊", "強勢"]) else (
            "#00E676" if any(k in str(zyg_status) for k in ["空頭", "防守", "弱勢"]) else "#FFFFFF"
        )

        c_kp = "#FF4D4D" if any(k in str(kp_status) for k in ["拉升", "建倉", "洗盤"]) else (
            "#00E676" if any(k in str(kp_status) for k in ["落體", "出貨"]) else "#FFFFFF"
        )

        is_above_workline = latest['Close'] >= latest.get('工作線', 0)
        workline_text = '線上(多)' if is_above_workline else '線下(空)'
        c_workline = "#FF4D4D" if is_above_workline else "#00E676"

        # 2. 產出 HTML
        status_card_html = f"""
        <div class="stock-info-card">
            <div class="metric-title">🎯 主力控盤與多空趨勢</div>
            <div class="metric-row">
                <span class="metric-label" style="color: #9B9B9B;">控盤狀態</span>
                <span class="metric-value" style="color: {c_control}; font-weight: bold;">{control_status}</span>
            </div>
            <div class="metric-row">
                <span class="metric-label" style="color: #9B9B9B;">ZYG趨勢</span>
                <span class="metric-value" style="color: {c_zyg}; font-weight: bold;">{zyg_status}</span>
            </div>
            <div class="metric-row">
                <span class="metric-label" style="color: #9B9B9B;">操盤階段</span>
                <span class="metric-value" style="color: {c_kp}; font-weight: bold;">{kp_status}</span>
            </div>
            <div class="metric-row">
                <span class="metric-label" style="color: #9B9B9B;">工作線多空</span>
                <span class="metric-value" style="color: {c_workline}; font-weight: bold;">{workline_text}</span>
            </div>
        </div>
        """
        st.sidebar.markdown(status_card_html, unsafe_allow_html=True)

        # 法人動態表卡片
        html_table = f"""
        <div class="stock-info-card" style="padding: 8px 3px;">
            <div class="metric-title">📊 近 7 日三大法人買賣超 (張/口)</div>
            <table style="width: 100%; font-size: 11px; border-collapse: collapse; font-family: monospace;">
                <thead>
                    <tr style="border-bottom: 1px solid #444444; color: #888888; text-align: right;">
                        <th style="text-align: left;">日期</th><th>外資</th><th>投信</th><th>自營</th><th>合計</th>
                    </tr>
                </thead>
                <tbody>{table_rows}</tbody>
            </table>
        </div>
        """
        st.sidebar.markdown(html_table, unsafe_allow_html=True)

        # 頂部大字標題 (採用 global_prev_close 計算全天累積漲跌)
        latest_close = float(latest["Close"])
        base_prev = global_prev_close if global_prev_close > 0 else latest_close
        
        change = latest_close - base_prev
        pct_change = (change / base_prev) * 100 if base_prev > 0 else 0.0
        p_color = "#FF3333" if change > 0 else ("#00FF66" if change < 0 else "#CCCCCC")
        sign = "+" if change > 0 else ""

        pc_header_html = f"""
        <div style="background-color: #1E222D; border: 1px solid #2A2E39; border-radius: 6px; padding: 20px 24px; margin-bottom: 2px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: nowrap; white-space: nowrap;">
                <div style="display: flex; align-items: baseline; gap: 10px;">
                    <span style="font-size: 20px; font-weight: bold; color: #FFFFFF;">{stock_name} ({clean_code})</span>
                    <span style="color: #888888; font-size: 18px;">[{kline_type}]</span>
                    <span style="font-size: 24px; font-weight: bold; color: {p_color}; margin-left: 4px;">
                        {latest_close:,.2f} <span style="font-size: 16px;">({sign}{change:,.2f} / {sign}{pct_change:.2f}%)</span>
                    </span>
                </div>
                <div style="display: flex; align-items: center; gap: 16px; font-size: 13px; color: #CCCCCC;">
                    <div>EMA5: <b style="color:#FFF;">{latest.get('工作線', 0):,.2f}</b></div>
                    <div>MA10: <b style="color:#FFF;">{latest.get('MA10', 0):,.2f}</b></div>
                    <div>MA20: <b style="color:#FFF;">{latest.get('MA20', 0):,.2f}</b></div>
                    <div>MA60: <b style="color:#FFF;">{latest.get('MA60', 0):,.2f}</b></div>
                    <div>成交量: <b style="color:#FFF;">{int(latest['Volume']):,}</b></div>
                    <div>控盤值: <b style="color:#FFF;">{latest.get('控盤', 0):.2f}</b></div>
                </div>
            </div>
        </div>
        """
        st.markdown(pc_header_html, unsafe_allow_html=True)

        render_risk_card(df)
        render_echarts_html(df, height=1050, sub1_metric=sub1_metric)

    else:
        st.error(f"查無 {clean_code} 在 {kline_type} 下的數據，請確認 `data_fetcher.py` 數據源接口。")
