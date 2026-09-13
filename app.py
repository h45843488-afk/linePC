# app_2.py
import importlib
import custom_indicator
import dynamic_subchart
import exp
import medium_long_term_wave
importlib.reload(custom_indicator)
importlib.reload(dynamic_subchart)
importlib.reload(exp)
importlib.reload(medium_long_term_wave)  # 加上這行，確保每次儲存重新整理都讀到最新的 exp.py[cite: 2]

from dynamic_subchart import get_subchart_data, get_subchart_echarts_config
import base64
import datetime
import json
import time
import numpy as np
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from data_fetcher import fetch_60min_kline, get_realtime_dde
from risk_card import render_risk_card


def render_html_iframe(
    html_code: str, height: int = 600, scrolling: bool = False
):
    """將 HTML 字串轉為 base64 URI 並透過 st.iframe 渲染"""[cite: 2]
    b64_html = base64.b64encode(html_code.encode("utf-8")).decode("utf-8")
    data_url = f"data:text/html;charset=utf-8;base64,{b64_html}"
    st.iframe(src=data_url, height=height, scrolling=scrolling)


# ---------------------------------------------------------
# 1. 頁面配置與樣式 (電腦版設定)
# ---------------------------------------------------------
st.set_page_config(
    page_title="台股 K 線監控站",
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
    .metric-title { font-size: 13px; color: #888888; font-weight: bold; margin-bottom: 5px; }
    .metric-row { display: flex; justify-content: space-between; font-size: 13px; padding: 3px 0; border-bottom: 1px dashed #2A2E39; }
    .metric-label { color: #CCCCCC; }
    .metric-value { font-weight: bold; color: #FFFFFF; }
    
    /* 電腦版抬頭樣式 */
    .pc-header-card {
        background-color: #1E222D;
        border: 1px solid #2A2E39;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
    }
    .pc-header-title {
        font-size: 24px;
        font-weight: bold;
        color: #FFFFFF;
    }
    .pc-header-price {
        font-size: 28px;
        font-weight: bold;
    }
    </style>
""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# 2. 抓取股票數據與三大法人籌碼 (FinMind REST API)
# ---------------------------------------------------------
@st.cache_data(ttl=3600)
def get_stock_name(stock_code):
    clean_code = str(stock_code).strip().replace(".TW", "").replace(".TWO", "")
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


@st.cache_data
def fetch_stock_meta_and_kline(input_code):
    """抓取歷史日 K 數據，天數拉長至 4 年以利週 K 與月 K 計算長均線"""
    clean_code = str(stock_code).strip().replace(".TW", "").replace(".TWO", "")
    stock_name = get_stock_name(clean_code)

    end_date = datetime.date.today().strftime("%Y-%m-%d")
    start_date = (
        datetime.date.today() - datetime.timedelta(days=365 * 4)
    ).strftime("%Y-%m-%d")

    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": clean_code,
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
        df["Volume"] = (df["Volume"] / 1000).astype(int)

        return stock_name, clean_code, df

    except Exception as e:
        st.sidebar.error(f"資料讀取失敗: {e}")
        return stock_name, clean_code, pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_institutional_data(stock_code):
    clean_code = str(stock_code).strip().replace(".TW", "").replace(".TWO", "")
    start_date = (
        datetime.date.today() - datetime.timedelta(days=15)
    ).strftime("%Y-%m-%d")
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockInstitutionalInvestorsBuySell",
        "data_id": clean_code,
        "start_date": start_date,
    }

    try:
        time.sleep(0.1)
        res = requests.get(url, params=params, timeout=8)
        data = res.json()

        if data.get("msg") != "success" or not data.get("data"):
            return pd.DataFrame(
                [["無資料", 0, 0, 0, 0]],
                columns=["日期", "外資", "投信", "自營商", "合計"],
            )

        df_raw = pd.DataFrame(data["data"])
        df_raw["buy_sell_sheet"] = (df_raw["buy"] - df_raw["sell"]) / 1000

        def categorize(name):
            if "Foreign" in name:
                return "外資"
            elif "Investment_Trust" in name:
                return "投信"
            elif "Dealer" in name:
                return "自營商"
            return "其他"

        df_raw["法人類別"] = df_raw["name"].apply(categorize)

        df_pivot = df_raw.pivot_table(
            index="date",
            columns="法人類別",
            values="buy_sell_sheet",
            aggfunc="sum",
        ).fillna(0)

        for col in ["外資", "投信", "自營商"]:
            if col not in df_pivot.columns:
                df_pivot[col] = 0

        for col in ["外資", "投信", "自營商"]:
            df_pivot[col] = np.round(df_pivot[col]).astype(int)

        df_pivot["合計"] = (
            df_pivot["外資"] + df_pivot["投信"] + df_pivot["自營商"]
        )

        df_result = df_pivot.tail(7).iloc[::-1].reset_index()
        df_result.rename(columns={"date": "日期"}, inplace=True)
        df_result["日期"] = pd.to_datetime(df_result["日期"]).dt.strftime(
            "%m/%d"
        )

        return df_result[["日期", "外資", "投信", "自營商", "合計"]]

    except Exception as e:
        return pd.DataFrame(
            [["網路異常", 0, 0, 0, 0]],
            columns=["日期", "外資", "投信", "自營商", "合計"],
        )


# ---------------------------------------------------------
# 日 K 即時資料合併與週/月 K 轉換函數
# ---------------------------------------------------------
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
    high = (
        realtime_data.get("high")
        or realtime_data.get("h")
        or realtime_data.get("max")
        or price
    )
    low = (
        realtime_data.get("low")
        or realtime_data.get("l")
        or realtime_data.get("min")
        or price
    )
    open_price = (
        realtime_data.get("open") or realtime_data.get("o") or price
    )
    volume = (
        realtime_data.get("volume")
        or realtime_data.get("v")
        or realtime_data.get("tv")
        or 0
    )

    if price is None:
        return df_res

    price = float(price)
    high = float(high) if high is not None else price
    low = float(low) if low is not None else price
    open_price = float(open_price) if open_price is not None else price
    volume = int(volume)

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
    """重採樣為週 K (W-FRI) 或月 K (ME)"""
    if df_daily.empty:
        return df_daily

    df = df_daily.copy()
    df["Date"] = pd.to_datetime(df["DateStr"])
    df.set_index("Date", inplace=True)

    rule = "W-FRI" if timeframe == "W" else "ME"

    resampled = (
        df.resample(rule)
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna(subset=["Close"])
        .reset_index()
    )

    resampled["DateStr"] = resampled["Date"].dt.strftime("%Y-%m-%d")
    return resampled.drop(columns=["Date"])


# ---------------------------------------------------------
# 3. 技術指標計算 (含資金爆發、波段拐點、吸拉派落與莊家控盤)
# ---------------------------------------------------------
def ema_func(series, period):
    return series.ewm(span=period, adjust=False, min_periods=0).mean()


def calculate_custom_indicators(df):
    if df.empty or len(df) < 5:
        return df

    df = df.copy()

    # === 資金爆發計算 ===
    var1_fund = (df["Close"] - df["Close"].shift(1)) / df["Close"].shift(1) * 100
    var2_fund = (df["Close"] - df["Low"].rolling(9).min()) / (df["High"].rolling(9).max() - df["Low"].rolling(9).min()) * 100
    var3_fund = var2_fund.ewm(span=3, adjust=False).mean()
    var4_fund = var3_fund.ewm(span=3, adjust=False).mean()
    var5_fund = var4_fund.ewm(span=3, adjust=False).mean()
    df["資金爆發"] = np.where((var1_fund > 3) & (var5_fund < 80), var1_fund * 10, 0)

    # === 波段拐點(13,6) + 中期安全線(55) ===
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

    # === 吸拉派落計算 ===
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

    # === 黃色多頭帶計算 ===
    df["JJ"] = (df["Close"] + df["High"] + df["Low"]) / 3
    df["E"] = df["JJ"].ewm(span=5, adjust=False).mean()
    df["D"] = df["E"].shift(1)
    df["E_gt_D"] = df["E"] > df["D"]

    # === 基礎均線與 MACD ===
    df["工作線"] = df["Close"].ewm(span=5, adjust=False).mean()
    df["MA10"] = df["Close"].rolling(10, min_periods=1).mean()
    df["MA20"] = df["Close"].rolling(20, min_periods=1).mean()
    df["MA60"] = df["Close"].rolling(60, min_periods=1).mean()

    df["CROSS_GOLDEN"] = (df["工作線"] > df["MA20"]) & (
        df["工作線"].shift(1) <= df["MA20"].shift(1)
    )

    ema8 = df["Close"].ewm(span=8, adjust=False).mean()
    ema13 = df["Close"].ewm(span=13, adjust=False).mean()
    df["DIF"] = ema8 - ema13
    df["MACD"] = df["DIF"].ewm(span=5, adjust=False).mean()
    df["MACD_Hist"] = (df["DIF"] - df["MACD"]) * 2

    # === 趨勢紅綠線與買賣訊號 ===
    zyg28 = df["Close"]
    zyg_sma1 = zyg28.ewm(alpha=1 / 2, adjust=False).mean()
    zyg_sma2 = zyg_sma1.ewm(alpha=1 / 2, adjust=False).mean()
    df["ZYG29"] = zyg_sma2.ewm(alpha=1 / 2, adjust=False).mean()
    df["ZYG30"] = df["ZYG29"].rolling(window=3, min_periods=1).mean()
    df["ZYG_Red"] = np.where(df["ZYG29"] > df["ZYG30"], df["ZYG29"], None)
    df["ZYG_Green"] = np.where(df["ZYG29"] <= df["ZYG30"], df["ZYG29"], None)

    df["ZYG_CROSS_BUY"] = (df["ZYG29"] > df["ZYG30"]) & (
        df["ZYG29"].shift(1) <= df["ZYG30"].shift(1)
    )
    vol_ma5 = df["Volume"].rolling(window=5, min_periods=1).mean()
    df["V_UP"] = df["Volume"] > (vol_ma5 * 1.3)
    df["TREND_OK"] = df["Close"] > df["MA20"]
    df["REF_HHV10"] = df["High"].shift(1).rolling(window=10, min_periods=1).max()
    df["BREAK_BOX"] = df["Close"] > df["REF_HHV10"]

    df["HIGH_WIN_BUY"] = (
        df["ZYG_CROSS_BUY"] & df["V_UP"] & df["TREND_OK"] & df["BREAK_BOX"]
    )
    df["BASE_GD"] = df["ZYG_CROSS_BUY"] & (~df["HIGH_WIN_BUY"])
    df["SELL_ALL"] = (df["ZYG29"] <= df["ZYG30"]) & (
        df["ZYG29"].shift(1) > df["ZYG30"].shift(1)
    )

    df["Signal_Text"] = None
    df["Signal_Color"] = None
    for i in range(len(df)):
        if df.iloc[i]["HIGH_WIN_BUY"]:
            df.iat[i, df.columns.get_loc("Signal_Text")] = "突破"
            df.iat[i, df.columns.get_loc("Signal_Color")] = "#FF00FF"
        elif df.iloc[i]["BASE_GD"]:
            df.iat[i, df.columns.get_loc("Signal_Text")] = "轉折"
            df.iat[i, df.columns.get_loc("Signal_Color")] = "#FFD700"

    # === 量能主力線 ===
    df["主力啟動線"] = df["Volume"].rolling(5, min_periods=1).mean()
    df["主力洗盤線"] = df["Volume"].rolling(35, min_periods=1).mean()
    df["資金異動線"] = df["Volume"].rolling(120, min_periods=1).mean()

    cross_start_fund = (df["主力啟動線"] > df["資金異動線"]) & (
        df["主力啟動線"].shift(1) <= df["資金異動線"].shift(1)
    )
    cross_start_wash = (df["主力啟動線"] > df["主力洗盤線"]) & (
        df["主力啟動線"].shift(1) <= df["主力洗盤線"].shift(1)
    )
    df["VOL_出擊"] = cross_start_fund | (
        (df["主力洗盤線"] > df["資金異動線"]) & cross_start_wash
    )

    cross_vol_start = (df["Volume"] > df["主力啟動線"]) & (
        df["Volume"].shift(1) <= df["主力啟動線"].shift(1)
    )
    ref_vol_low = (df["Volume"].shift(1) < df["資金異動線"].shift(1)) | (
        df["Volume"].shift(2) < df["資金異動線"].shift(2)
    )
    df["VOL_啟動"] = (
        (df["主力啟動線"] > df["主力啟動線"].shift(1))
        & cross_vol_start
        & ref_vol_low
    )

    df["V1"] = (df["Close"] / df["Close"].shift(3)) >= 1.10
    v1_forward = df["V1"].shift(-1).fillna(False)
    df["VOL_OK"] = df["V1"] | v1_forward

    # === 莊家控盤 ===
    var1_ema1 = df["Close"].ewm(span=9, adjust=False).mean()
    var1 = var1_ema1.ewm(span=9, adjust=False).mean()

    var1_ref1 = var1.shift(1)
    df["控盤"] = np.where(
        var1_ref1 != 0, (var1 - var1_ref1) / var1_ref1 * 1000, 0
    )
    df["控盤_REF"] = df["控盤"].shift(1)

    df["AA0"] = (df["控盤"] > 0) & (df["控盤_REF"] <= 0)
    df["開始控盤"] = np.where(df["AA0"], 5.0, 0.0)

    low_60 = df["Low"].rolling(window=60, min_periods=1).min()
    high_60 = df["High"].rolling(window=60, min_periods=1).max()
    price_range = np.where((high_60 - low_60) == 0, 1, high_60 - low_60)

    winner_95 = np.clip(
        (df["Close"] * 0.95 - low_60) / price_range * 100, 0, 100
    )
    cost_85 = low_60 + price_range * 0.85

    df["無莊控盤"] = df["控盤"] < 0
    df["有莊控盤"] = (df["控盤"] > df["控盤_REF"]) & (df["控盤"] > 0)
    df["高度控盤"] = (
        (winner_95 > 50) & (df["Close"] > cost_85) & (df["控盤"] > 0)
    )
    df["主力出貨"] = (df["控盤"] < df["控盤_REF"]) & (df["控盤"] > 0)

    return df


# ---------------------------------------------------------
# 4A. ECharts 60分鐘K渲染器
# ---------------------------------------------------------
def render_echarts_html_60(df, height=1050, sub1_metric="資金爆發"):
    if df is None or df.empty:
        return "<div style='color:white;padding:20px;'>沒有60分鐘K資料</div>"

    df = calculate_custom_indicators(df)

    for col in ["Open", "High", "Low", "Close", "Volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Open", "High", "Low", "Close"]).reset_index(
        drop=True
    )

    if df.empty:
        return "<div style='color:white;padding:20px;'>60分鐘K資料無效</div>"

    # 1. 均線與量能主力線
    df["EMA5_60"] = df["Close"].ewm(span=5, adjust=False).mean()
    df["MA10_60"] = df["Close"].rolling(window=10, min_periods=1).mean()
    df["MA20_60"] = df["Close"].rolling(window=20, min_periods=1).mean()
    df["MA60_60"] = df["Close"].rolling(window=60, min_periods=1).mean()

    df["CROSS_GOLDEN_60"] = (df["EMA5_60"] > df["MA20_60"]) & (
        df["EMA5_60"].shift(1) <= df["MA20_60"].shift(1)
    )

    df["主力啟動線_60"] = df["Volume"].rolling(window=5, min_periods=1).mean()
    df["主力洗盤線_60"] = df["Volume"].rolling(window=35, min_periods=1).mean()
    df["資金異動線_60"] = (
        df["Volume"].rolling(window=120, min_periods=1).mean()
    )

    df["VOL_OK_60"] = df["Volume"] > df["主力啟動線_60"] * 1.3
    df["VOL_出擊_60"] = df["主力啟動線_60"] > df["主力洗盤線_60"]
    df["VOL_啟動_60"] = (df["Volume"] > df["主力啟動線_60"]) & (
        df["主力啟動線_60"] > df["主力啟動線_60"].shift(1)
    )

    # 2. 黃色多頭帶
    df["JJ_60"] = (df["Close"] + df["High"] + df["Low"]) / 3
    df["E_60"] = df["JJ_60"].ewm(span=5, adjust=False).mean()
    df["D_60"] = df["E_60"].shift(1)
    df["E_gt_D_60"] = df["E_60"] > df["D_60"]

    # 3. ZYG 趨勢線
    zyg28_60 = df["Close"]
    zyg_sma1_60 = zyg28_60.ewm(alpha=1 / 2, adjust=False).mean()
    zyg_sma2_60 = zyg_sma1_60.ewm(alpha=1 / 2, adjust=False).mean()
    df["ZYG29_60"] = zyg_sma2_60.ewm(alpha=1 / 2, adjust=False).mean()
    df["ZYG30_60"] = df["ZYG29_60"].rolling(window=3, min_periods=1).mean()

    df["ZYG_Red_60"] = np.where(
        df["ZYG29_60"] > df["ZYG30_60"], df["ZYG29_60"], np.nan
    )
    df["ZYG_Green_60"] = np.where(
        df["ZYG29_60"] <= df["ZYG30_60"], df["ZYG29_60"], np.nan
    )

    df["ZYG_CROSS_BUY_60"] = (df["ZYG29_60"] > df["ZYG30_60"]) & (
        df["ZYG29_60"].shift(1) <= df["ZYG30_60"].shift(1)
    )
    df["ZYG_SELL_60"] = (df["ZYG29_60"] <= df["ZYG30_60"]) & (
        df["ZYG29_60"].shift(1) > df["ZYG30_60"].shift(1)
    )

    # 4. 突破訊號
    vol_ma5_60 = df["Volume"].rolling(window=5, min_periods=1).mean()
    df["V_UP_60"] = df["Volume"] > vol_ma5_60 * 1.3
    df["TREND_OK_60"] = df["Close"] > df["MA20_60"]
    df["REF_HHV10_60"] = (
        df["High"].shift(1).rolling(window=10, min_periods=1).max()
    )
    df["BREAK_BOX_60"] = df["Close"] > df["REF_HHV10_60"]

    df["HIGH_WIN_BUY_60"] = (
        df["ZYG_CROSS_BUY_60"]
        & df["V_UP_60"]
        & df["TREND_OK_60"]
        & df["BREAK_BOX_60"]
    )
    df["BASE_GD_60"] = df["ZYG_CROSS_BUY_60"] & (~df["HIGH_WIN_BUY_60"])

    # 5. 「莊家抬轎」指標計算 (60分K)
    var1_ema1_60 = df["Close"].ewm(span=9, adjust=False).mean()
    var1_60 = var1_ema1_60.ewm(span=9, adjust=False).mean()
    var1_ref1_60 = var1_60.shift(1)
    df["控盤_60"] = np.where(
        var1_ref1_60 != 0, (var1_60 - var1_ref1_60) / var1_ref1_60 * 1000, 0
    )
    df["控盤_REF_60"] = df["控盤_60"].shift(1)

    df["AA0_60"] = (df["控盤_60"] > 0) & (df["控盤_REF_60"] <= 0)
    df["開始控盤_60"] = np.where(df["AA0_60"], 5.0, 0.0)

    low_60 = df["Low"].rolling(window=60, min_periods=1).min()
    high_60 = df["High"].rolling(window=60, min_periods=1).max()
    price_range_60 = np.where((high_60 - low_60) == 0, 1, high_60 - low_60)

    winner_95_60 = np.clip(
        (df["Close"] * 0.95 - low_60) / price_range_60 * 100, 0, 100
    )
    cost_85_60 = low_60 + price_range_60 * 0.85

    df["高度控盤_60"] = (
        (winner_95_60 > 50) & (df["Close"] > cost_85_60) & (df["控盤_60"] > 0)
    )
    df["有莊控盤_60"] = (df["控盤_60"] > df["控盤_REF_60"]) & (
        df["控盤_60"] > 0
    )
    df["主力出貨_60"] = (df["控盤_60"] < df["控盤_REF_60"]) & (
        df["控盤_60"] > 0
    )

    # 6. 「吸拉派落」指標計算 (60分K)
    ema13_60 = df["Close"].ewm(span=13, adjust=False).mean()
    vara_60 = ema13_60.ewm(span=13, adjust=False).mean()
    vara_prev_60 = vara_60.shift(1)

    kp_60 = (vara_60 - vara_prev_60) / vara_prev_60 * 1000
    df["KP_60"] = kp_60
    mm_60 = kp_60.shift(1)
    df["MM_60"] = mm_60

    df["派_60"] = kp_60
    df["落_60"] = np.where(kp_60 < 0, kp_60, np.nan)
    df["吸_60"] = np.where(kp_60 >= mm_60, kp_60, np.nan)
    df["拉_60"] = np.where((kp_60 >= 0) & (kp_60 >= mm_60), kp_60, np.nan)

    # 7. MACD 正確計算 (8, 13, 5)
    ema8_macd = df["Close"].ewm(span=8, adjust=False).mean()
    ema13_macd = df["Close"].ewm(span=13, adjust=False).mean()
    df["DIF_60"] = ema8_macd - ema13_macd
    df["DEA_60"] = df["DIF_60"].ewm(span=5, adjust=False).mean()
    df["MACD_Hist_60"] = (df["DIF_60"] - df["DEA_60"]) * 2

    macd_data = [
        {
            "value": round(float(x), 2) if pd.notna(x) else 0,
            "itemStyle": {
                "color": "#FF3333" if (pd.notna(x) and x >= 0) else "#00AA00"
            },
        }
        for x in df["MACD_Hist_60"]
    ]

    def clean_list(series):
        return [None if pd.isna(x) else round(float(x), 2) for x in series]

    # 從 dynamic_subchart.py / exp.py 動態讀取副圖一
    if sub1_metric == "資金爆發":
        sub1_series = get_subchart_data(df, metric_name="主力資金")
    elif sub1_metric in ["波段拐點", "波段起爆點"]:
        sub1_series = exp.get_explosion_subchart_data(df)
    elif sub1_metric == "六脈神劍":
        df_six = custom_indicator.tdx_resonance_strategy(df)
        sub1_series = get_subchart_data(df_six, metric_name="六脈神劍")
    elif sub1_metric == "中長期波段":
        df_wave = medium_long_term_wave.get_medium_long_term_wave_data(df)
        def make_continuous_direction_line(values, mask, other_mask=None):
            values = np.asarray(values, dtype=float)
            mask = pd.Series(mask).fillna(False).to_numpy(dtype=bool)
            out = np.full(len(values), np.nan, dtype=float)
            out[mask] = values[mask]

            # 只在方向真正切換的當天補「交接點」。
            # 舊方向線補到切換日，新方向線也從切換日開始，
            # 兩條線在同一天相接；絕不把新方向提前到前一天。
            if other_mask is not None:
                other_mask = pd.Series(other_mask).fillna(False).to_numpy(dtype=bool)
                for j in range(1, len(out)):
                    if (not mask[j]) and mask[j - 1] and other_mask[j]:
                        out[j] = values[j]

            return out

        long_up_data = make_continuous_direction_line(
            df_wave["長期波動"],
            df_wave["長期方向上升"],
            df_wave["長期方向下降"],
        )
        long_down_data = make_continuous_direction_line(
            df_wave["長期波動"],
            df_wave["長期方向下降"],
            df_wave["長期方向上升"],
        )
        medium_up_data = make_continuous_direction_line(
            df_wave["中期波動"],
            df_wave["中級方向上升"],
            df_wave["中級方向下降"],
        )
        medium_down_data = make_continuous_direction_line(
            df_wave["中期波動"],
            df_wave["中級方向下降"],
            df_wave["中級方向上升"],
        )

        hzs_points = []
        lzs_points = []
        for i, row in df_wave.iterrows():
            date_str = str(row["DateStr"])
            if bool(row.get("HZS", False)):
                hzs_points.append({
                    "name": "HZS",
                    "coord": [date_str, float(row["長期波動"])],
                    "value": "買入",
                    "symbol": "arrow",
                    "symbolSize": 10,
                    "itemStyle": {"color": "#FF3333"},
                    "label": {"position": "bottom", "color": "#FF3333", "fontSize": 10},
                })
            if bool(row.get("LZS", False)):
                lzs_points.append({
                    "name": "LZS",
                    "coord": [date_str, float(row["長期波動"])],
                    "value": "賣出",
                    "symbol": "arrow",
                    "symbolSize": 10,
                    "symbolRotate": 180,
                    "itemStyle": {"color": "#00CC66"},
                    "label": {"position": "top", "color": "#00CC66", "fontSize": 10},
                })

        sub1_series = [
            {"name": "長期方向上升", "type": "line", "data": clean_list(long_up_data), "xAxisIndex": 1, "yAxisIndex": 1, "showSymbol": False, "connectNulls": False, "lineStyle": {"color": "#FF3333", "width": 4}, "markPoint": {"data": hzs_points}},
            {"name": "長期方向下降", "type": "line", "data": clean_list(long_down_data), "xAxisIndex": 1, "yAxisIndex": 1, "showSymbol": False, "connectNulls": False, "lineStyle": {"color": "#00CC66", "width": 4,}, "markPoint": {"data": lzs_points}},
            {"name": "中級方向上升", "type": "line", "data": clean_list(medium_up_data), "xAxisIndex": 1, "yAxisIndex": 1, "showSymbol": False, "connectNulls": False, "lineStyle": {"color": "#FF6666", "width": 2}},
            {"name": "中級方向下降", "type": "line", "data": clean_list(medium_down_data), "xAxisIndex": 1, "yAxisIndex": 1, "showSymbol": False, "connectNulls": False, "lineStyle": {"color": "#00AA55", "width": 2}},
        ]
    else:
        sub1_series = get_subchart_data(df, sub1_metric)

    # 8. 基礎數據轉換
    dates = df["DateStr"].astype(str).tolist()

    k_values = []
    for _, row in df.iterrows():
        open_val = round(float(row["Open"]), 2)
        close_val = round(float(row["Close"]), 2)
        low_val = round(float(row["Low"]), 2)
        high_val = round(float(row["High"]), 2)

        if row.get("CROSS_GOLDEN_60", False):
            k_values.append({
                "value": [open_val, close_val, low_val, high_val],
                "itemStyle": {
                    "color": "#FFFFFF",
                    "color0": "#FFFFFF",
                    "borderColor": "#FFFFFF",
                    "borderColor0": "#FFFFFF",
                },
            })
        else:
            k_values.append([open_val, close_val, low_val, high_val])

    yellow_bar_data = []
    for _, row in df.iterrows():
        if row["E_gt_D_60"] and pd.notna(row["D_60"]):
            d_val = round(float(row["D_60"]), 2)
            e_val = round(float(row["E_60"]), 2)
            yellow_bar_data.append([d_val, e_val, d_val, e_val])
        else:
            yellow_bar_data.append([None, None, None, None])

    mark_points = []
    for idx, row in df.iterrows():
        if bool(row["HIGH_WIN_BUY_60"]):
            mark_points.append({
                "name": "突破",
                "coord": [str(row["DateStr"]), float(row["Low"])],
                "value": "突破",
                "symbol": "arrow",
                "symbolSize": 10,
                "itemStyle": {"color": "#FF00FF"},
                "label": {
                    "position": "bottom",
                    "distance": 5,
                    "fontSize": 11,
                    "color": "#FF00FF",
                },
            })
        elif bool(row["BASE_GD_60"]):
            mark_points.append({
                "name": "轉折",
                "coord": [str(row["DateStr"]), float(row["Low"])],
                "value": "轉折",
                "symbol": "arrow",
                "symbolSize": 8,
                "itemStyle": {"color": "#FFD700"},
                "label": {
                    "position": "bottom",
                    "distance": 5,
                    "fontSize": 11,
                    "color": "#FFD700",
                },
            })
        if bool(row["ZYG_SELL_60"]):
            mark_points.append({
                "name": "賣點",
                "coord": [str(row["DateStr"]), float(row["High"])],
                "value": "賣點",
                "symbol": "arrow",
                "symbolSize": 8,
                "symbolRotate": 180,
                "itemStyle": {"color": "#00FF00"},
                "label": {
                    "position": "top",
                    "distance": 5,
                    "fontSize": 11,
                    "color": "#00FF00",
                },
            })

    volume_data = []
    vol_white_line_data = []
    for _, row in df.iterrows():
        vol_val = int(row["Volume"])
        if row["VOL_OK_60"]:
            color = "#FF0033"
        elif row["VOL_出擊_60"]:
            color = "#FFFF00"
        elif row["VOL_啟動_60"]:
            color = "#00FF00"
        else:
            color = "#CC2222" if row["Close"] >= row["Open"] else "#00AA00"

        volume_data.append({"value": vol_val, "itemStyle": {"color": color}})
        vol_white_line_data.append(vol_val if row["VOL_OK_60"] else None)

    zhuang_data_60 = []
    kaishi_line_data_60 = []
    for idx, row in df.iterrows():
        val = round(float(row["控盤_60"]), 2) if pd.notna(row["控盤_60"]) else 0
        if row["高度控盤_60"]:
            color = "#FF00FF"
        elif row["有莊控盤_60"]:
            color = "#FF3333"
        elif row["主力出貨_60"]:
            color = "#00FF00"
        else:
            color = "#FFFFFF"

        zhuang_data_60.append({"value": val, "itemStyle": {"color": color}})
        kaishi_line_data_60.append(5.0 if row["AA0_60"] else 0.0)

    total_len = len(dates)
    start_percent = int((1 - 70 / total_len) * 100) if total_len > 70 else 0

    series_list = [
        {
            "name": "黃色多頭帶",
            "type": "candlestick",
            "data": yellow_bar_data,
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "z": 1,
            "itemStyle": {
                "color": "#FFFF00",
                "color0": "#FFFF00",
                "borderColor": "#FFFF00",
                "borderColor0": "#FFFF00",
            },
        },
        {
            "name": "60分K",
            "type": "candlestick",
            "data": k_values,
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "z": 2,
            "itemStyle": {
                "color": "#FF3333",
                "color0": "#00AA00",
                "borderColor": "#FF3333",
                "borderColor0": "#00AA00",
            },
            "markPoint": {"data": mark_points},
        },
        {
            "name": "EMA5",
            "type": "line",
            "data": clean_list(df["EMA5_60"]),
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFFFF", "width": 1},
        },
        {
            "name": "MA10",
            "type": "line",
            "data": clean_list(df["MA10_60"]),
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFF00", "width": 1},
        },
        {
            "name": "MA20",
            "type": "line",
            "data": clean_list(df["MA20_60"]),
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "showSymbol": False,
            "lineStyle": {"color": "#FF1493", "width": 1},
        },
        {
            "name": "MA60",
            "type": "line",
            "data": clean_list(df["MA60_60"]),
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "showSymbol": False,
            "lineStyle": {"color": "#00FFFF", "width": 1},
        },
        {
            "name": "趨勢紅線",
            "type": "line",
            "data": clean_list(df["ZYG_Red_60"]),
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "showSymbol": False,
            "connectNulls": False,
            "lineStyle": {"color": "#FF0055", "width": 3},
        },
        {
            "name": "趨勢綠線",
            "type": "line",
            "data": clean_list(df["ZYG_Green_60"]),
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "showSymbol": False,
            "connectNulls": False,
            "lineStyle": {"color": "#00FF66", "width": 3},
        },
    ]

    # 加入動態副圖一配置
    series_list.extend(sub1_series)

    # 副圖二至副圖五配置
    series_list.extend([
        # === 副圖二：成交量 ===
        {
            "name": "成交量",
            "type": "bar",
            "data": volume_data,
            "xAxisIndex": 2,
            "yAxisIndex": 2,
        },
        {
            "name": "OK白線",
            "type": "bar",
            "data": vol_white_line_data,
            "xAxisIndex": 2,
            "yAxisIndex": 2,
            "barWidth": 6,
            "barGap": "-100%",
            "z": 10,
            "itemStyle": {"color": "#FFFFFF"},
        },
        {
            "name": "主力啟動線(5)",
            "type": "line",
            "data": clean_list(df["主力啟動線_60"]),
            "xAxisIndex": 2,
            "yAxisIndex": 2,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFFFF", "width": 1},
        },
        {
            "name": "主力洗盤線(35)",
            "type": "line",
            "data": clean_list(df["主力洗盤線_60"]),
            "xAxisIndex": 2,
            "yAxisIndex": 2,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFF00", "width": 1},
        },
        {
            "name": "資金異動線(120)",
            "type": "line",
            "data": clean_list(df["資金異動線_60"]),
            "xAxisIndex": 2,
            "yAxisIndex": 2,
            "showSymbol": False,
            "lineStyle": {"color": "#00FF00", "width": 1},
        },
        # === 副圖三：MACD ===
        {
            "name": "MACD",
            "type": "bar",
            "data": macd_data,
            "xAxisIndex": 3,
            "yAxisIndex": 3,
        },
        {
            "name": "DIF",
            "type": "line",
            "data": clean_list(df["DIF_60"]),
            "xAxisIndex": 3,
            "yAxisIndex": 3,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFFFF", "width": 1},
        },
        {
            "name": "DEA",
            "type": "line",
            "data": clean_list(df["DEA_60"]),
            "xAxisIndex": 3,
            "yAxisIndex": 3,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFF00", "width": 1},
        },
        # === 副圖四：莊家控盤 ===
        {
            "name": "莊家控盤",
            "type": "bar",
            "data": zhuang_data_60,
            "xAxisIndex": 4,
            "yAxisIndex": 4,
        },
        {
            "name": "開始控盤",
            "type": "line",
            "data": kaishi_line_data_60,
            "xAxisIndex": 4,
            "yAxisIndex": 4,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFF00", "width": 2},
        },
        # === 副圖五：吸拉派落 ===
        {
            "name": "MM",
            "type": "line",
            "data": clean_list(df["MM_60"]),
            "xAxisIndex": 5,
            "yAxisIndex": 5,
            "showSymbol": False,
            "lineStyle": {"color": "#888888", "width": 1, "type": "dashed"},
        },
        {
            "name": "派",
            "type": "line",
            "data": clean_list(df["派_60"]),
            "xAxisIndex": 5,
            "yAxisIndex": 5,
            "showSymbol": False,
            "lineStyle": {"color": "#00FF00", "width": 2},
        },
        {
            "name": "落",
            "type": "line",
            "data": clean_list(df["落_60"]),
            "xAxisIndex": 5,
            "yAxisIndex": 5,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFFFF", "width": 2},
        },
        {
            "name": "吸",
            "type": "line",
            "data": clean_list(df["吸_60"]),
            "xAxisIndex": 5,
            "yAxisIndex": 5,
            "showSymbol": False,
            "lineStyle": {"color": "#F08080", "width": 2},
        },
        {
            "name": "拉",
            "type": "line",
            "data": clean_list(df["拉_60"]),
            "xAxisIndex": 5,
            "yAxisIndex": 5,
            "showSymbol": False,
            "lineStyle": {"color": "#FF0000", "width": 2},
        },
    ])

    options = {
        "backgroundColor": "#131722",
        "animation": False,
        "tooltip": {"show": True, "trigger": "axis"},
        "grid": [
            {"left": "4%", "right": "3%", "top": "2%", "height": "30%"},   # 主K
            {"left": "4%", "right": "3%", "top": "34%", "height": "10%"},  # 副圖一
            {"left": "4%", "right": "3%", "top": "46%", "height": "10%"},  # 成交量
            {"left": "4%", "right": "3%", "top": "58%", "height": "10%"},  # MACD
            {"left": "4%", "right": "3%", "top": "70%", "height": "10%"},  # 莊家控盤
            {"left": "4%", "right": "3%", "top": "82%", "height": "10%"},  # 吸拉派落
        ],
        "xAxis": [
            {"type": "category", "data": dates, "gridIndex": 0, "axisLabel": {"show": True}},
            {"type": "category", "data": dates, "gridIndex": 1, "axisLabel": {"show": False}},
            {"type": "category", "data": dates, "gridIndex": 2, "axisLabel": {"show": False}},
            {"type": "category", "data": dates, "gridIndex": 3, "axisLabel": {"show": False}},
            {"type": "category", "data": dates, "gridIndex": 4, "axisLabel": {"show": False}},
            {"type": "category", "data": dates, "gridIndex": 5, "axisLabel": {"show": False}},
        ],
        "yAxis": [
            {"scale": True, "gridIndex": 0},
            {"scale": True, "gridIndex": 1, "splitLine": {"show": True, "lineStyle": {"color": "#2A2E39"}}},
            {"scale": True, "gridIndex": 2},
            {"scale": True, "gridIndex": 3},
            {"scale": True, "gridIndex": 4, "splitLine": {"show": True, "lineStyle": {"color": "#2A2E39"}}},
            {"scale": True, "gridIndex": 5, "splitLine": {"show": True, "lineStyle": {"color": "#2A2E39"}}},
        ],
        "dataZoom": [
            {
                "type": "inside",
                "xAxisIndex": [0, 1, 2, 3, 4, 5],
                "start": start_percent,
                "end": 100,
            },
            {
                "type": "slider",
                "xAxisIndex": [0, 1, 2, 3, 4, 5],
                "start": start_percent,
                "end": 100,
                "bottom": "1%",
            },
        ],
        "series": series_list,
    }

    options_json = json.dumps(options, ensure_ascii=False)

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
        <style>
            html, body {{
                margin: 0;
                padding: 0;
                width: 100%;
                height: 100%;
                background-color: #131722;
            }}
            #main {{
                width: 100%;
                height: {height}px;
            }}
        </style>
    </head>
    <body>
        <div id="main"></div>
        <script>
            var chartDom = document.getElementById("main");
            var myChart = echarts.init(chartDom, "dark");
            var option = {options_json};
            myChart.setOption(option);
            window.addEventListener("resize", function() {{
                myChart.resize();
            }});
        </script>
    </body>
    </html>
    """
    return html


# ---------------------------------------------------------
# 4B. ECharts 日/週/月 K 通用渲染器
# ---------------------------------------------------------
def render_echarts_html(df, height=1050, sub1_metric="資金爆發"):
    dates = df["DateStr"].tolist()

    def clean_list(series):
        return [None if pd.isna(x) else round(float(x), 2) for x in series]

    # 切換副圖一數據選擇
    if sub1_metric == "資金爆發":
        sub1_series = get_subchart_data(df, metric_name="主力資金")
    elif sub1_metric in ["波段拐點", "波段起爆點"]:
        sub1_series = exp.get_explosion_subchart_data(df)
    elif sub1_metric == "六脈神劍":
        df_six = custom_indicator.tdx_resonance_strategy(df)
        sub1_series = get_subchart_data(df_six, metric_name="六脈神劍")
    elif sub1_metric == "中長期波段":
        df_wave = medium_long_term_wave.get_medium_long_term_wave_data(df)
        def make_continuous_direction_line(values, mask, other_mask=None):
            values = np.asarray(values, dtype=float)
            mask = pd.Series(mask).fillna(False).to_numpy(dtype=bool)
            out = np.full(len(values), np.nan, dtype=float)
            out[mask] = values[mask]

            # 只在方向真正切換的當天補「交接點」。
            # 舊方向線補到切換日，新方向線也從切換日開始，
            # 兩條線在同一天相接；絕不把新方向提前到前一天。
            if other_mask is not None:
                other_mask = pd.Series(other_mask).fillna(False).to_numpy(dtype=bool)
                for j in range(1, len(out)):
                    if (not mask[j]) and mask[j - 1] and other_mask[j]:
                        out[j] = values[j]

            return out

        long_up_data = make_continuous_direction_line(
            df_wave["長期波動"],
            df_wave["長期方向上升"],
            df_wave["長期方向下降"],
        )
        long_down_data = make_continuous_direction_line(
            df_wave["長期波動"],
            df_wave["長期方向下降"],
            df_wave["長期方向上升"],
        )
        medium_up_data = make_continuous_direction_line(
            df_wave["中期波動"],
            df_wave["中級方向上升"],
            df_wave["中級方向下降"],
        )
        medium_down_data = make_continuous_direction_line(
            df_wave["中期波動"],
            df_wave["中級方向下降"],
            df_wave["中級方向上升"],
        )

        hzs_points = []
        lzs_points = []
        for i, row in df_wave.iterrows():
            date_str = str(row["DateStr"])
            if bool(row.get("HZS", False)):
                hzs_points.append({
                    "name": "HZS",
                    "coord": [date_str, float(row["長期波動"])],
                    "value": "買入",
                    "symbol": "arrow",
                    "symbolSize": 10,
                    "itemStyle": {"color": "#FF3333"},
                    "label": {"position": "bottom", "color": "#FF3333", "fontSize": 10},
                })
            if bool(row.get("LZS", False)):
                lzs_points.append({
                    "name": "LZS",
                    "coord": [date_str, float(row["長期波動"])],
                    "value": "賣出",
                    "symbol": "arrow",
                    "symbolSize": 10,
                    "symbolRotate": 180,
                    "itemStyle": {"color": "#00CC66"},
                    "label": {"position": "top", "color": "#00CC66", "fontSize": 10},
                })

        sub1_series = [
            {"name": "長期方向上升", "type": "line", "data": clean_list(long_up_data), "xAxisIndex": 1, "yAxisIndex": 1, "showSymbol": False, "connectNulls": False, "lineStyle": {"color": "#FF3333", "width": 4}, "markPoint": {"data": hzs_points}},
            {"name": "長期方向下降", "type": "line", "data": clean_list(long_down_data), "xAxisIndex": 1, "yAxisIndex": 1, "showSymbol": False, "connectNulls": False, "lineStyle": {"color": "#00CC66", "width": 4,}, "markPoint": {"data": lzs_points}},
            {"name": "中級方向上升", "type": "line", "data": clean_list(medium_up_data), "xAxisIndex": 1, "yAxisIndex": 1, "showSymbol": False, "connectNulls": False, "lineStyle": {"color": "#FF6666", "width": 2}},
            {"name": "中級方向下降", "type": "line", "data": clean_list(medium_down_data), "xAxisIndex": 1, "yAxisIndex": 1, "showSymbol": False, "connectNulls": False, "lineStyle": {"color": "#00AA55", "width": 2}},
        ]
    else:
        sub1_series = get_subchart_data(df, sub1_metric)

    k_values = []
    for _, row in df.iterrows():
        open_val = float(row["Open"])
        close_val = float(row["Close"])
        low_val = float(row["Low"])
        high_val = float(row["High"])

        if row.get("CROSS_GOLDEN", False):
            k_values.append({
                "value": [open_val, close_val, low_val, high_val],
                "itemStyle": {
                    "color": "#FFFFFF",
                    "color0": "#FFFFFF",
                    "borderColor": "#FFFFFF",
                    "borderColor0": "#FFFFFF",
                },
            })
        else:
            k_values.append([open_val, close_val, low_val, high_val])
            
    yellow_bar_data = []
    for _, row in df.iterrows():
        if row["E_gt_D"] and pd.notna(row["D"]):
            d_val = round(float(row["D"]), 2)
            e_val = round(float(row["E"]), 2)
            yellow_bar_data.append([d_val, e_val, d_val, e_val])
        else:
            yellow_bar_data.append([None, None, None, None])

    mark_points = []
    for idx, row in df.iterrows():
        if pd.notna(row["Signal_Text"]):
            mark_points.append({
                "name": str(row["Signal_Text"]),
                "coord": [str(row["DateStr"]), float(row["Low"])],
                "value": str(row["Signal_Text"]),
                "symbol": "arrow",
                "symbolSize": 8,
                "itemStyle": {"color": str(row["Signal_Color"])},
                "label": {
                    "position": "bottom",
                    "distance": 5,
                    "fontSize": 11,
                    "color": str(row["Signal_Color"]),
                },
            })
        if row["SELL_ALL"]:
            mark_points.append({
                "name": "賣點",
                "coord": [str(row["DateStr"]), float(row["High"])],
                "value": "賣點",
                "symbol": "arrow",
                "symbolSize": 8,
                "symbolRotate": 180,
                "itemStyle": {"color": "#00FF00"},
                "label": {
                    "position": "top",
                    "distance": 5,
                    "fontSize": 11,
                    "color": "#00FF00",
                },
            })

    vol_base_data = []
    vol_white_line_data = []

    for _, row in df.iterrows():
        vol_val = int(row["Volume"])

        if row["VOL_OK"]:
            color = "#FF0033"
        elif row["VOL_出擊"]:
            color = "#FFFF00"
        elif row["VOL_啟動"]:
            color = "#00FF00"
        else:
            color = "#CC2222" if row["Close"] >= row["Open"] else "#00AA00"

        vol_base_data.append({"value": vol_val, "itemStyle": {"color": color}})
        vol_white_line_data.append(vol_val if row["VOL_OK"] else None)

    macd_data = [
        {
            "value": round(float(row["MACD_Hist"]), 2),
            "itemStyle": {
                "color": "#FF3333" if row["MACD_Hist"] >= 0 else "#00AA00"
            },
        }
        for _, row in df.iterrows()
    ]

    zhuang_data = []
    kaishi_line_data = []

    for idx, row in df.iterrows():
        val = round(float(row["控盤"]), 2) if pd.notna(row["控盤"]) else 0
        if row["高度控盤"]:
            color = "#FF00FF"
        elif row["有莊控盤"]:
            color = "#FF3333"
        elif row["主力出貨"]:
            color = "#00FF00"
        else:
            color = "#FFFFFF"

        zhuang_data.append({"value": val, "itemStyle": {"color": color}})
        kaishi_line_data.append(5.0 if row["AA0"] else 0.0)

    total_len = len(dates)
    start_percent = (
        max(0, int((1 - 70 / total_len) * 100)) if total_len > 70 else 0
    )

    series_list = [
        {
            "name": "黃色多頭帶",
            "type": "candlestick",
            "data": yellow_bar_data,
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "z": 1,
            "itemStyle": {
                "color": "#FFFF00",
                "color0": "#FFFF00",
                "borderColor": "#FFFF00",
                "borderColor0": "#FFFF00",
            },
        },
        {
            "name": "K線",
            "type": "candlestick",
            "data": k_values,
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "z": 2,
            "itemStyle": {
                "color": "#FF3333",
                "color0": "#00AA00",
                "borderColor": "#FF3333",
                "borderColor0": "#00AA00",
            },
            "markPoint": {"data": mark_points},
        },
        {
            "name": "EMA5",
            "type": "line",
            "data": clean_list(df["工作線"]),
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFFFF", "width": 1},
        },
        {
            "name": "MA10",
            "type": "line",
            "data": clean_list(df["MA10"]),
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFF00", "width": 1},
        },
        {
            "name": "MA20",
            "type": "line",
            "data": clean_list(df["MA20"]),
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "showSymbol": False,
            "lineStyle": {"color": "#FF1493", "width": 1},
        },
        {
            "name": "MA60",
            "type": "line",
            "data": clean_list(df["MA60"]),
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "showSymbol": False,
            "lineStyle": {"color": "#00FFFF", "width": 1},
        },
        {
            "name": "趨勢紅線",
            "type": "line",
            "data": clean_list(df["ZYG_Red"]),
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "showSymbol": False,
            "lineStyle": {"color": "#FF0055", "width": 3},
        },
        {
            "name": "趨勢綠線",
            "type": "line",
            "data": clean_list(df["ZYG_Green"]),
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "showSymbol": False,
            "lineStyle": {"color": "#00FF66", "width": 3},
        },
    ]

    # 加入動態副圖一配置
    series_list.extend(sub1_series)

    # 副圖二至副圖五配置
    series_list.extend([
        # === 副圖二：成交量 ===
        {
            "name": "成交量",
            "type": "bar",
            "data": vol_base_data,
            "xAxisIndex": 2,
            "yAxisIndex": 2,
        },
        {
            "name": "OK白線",
            "type": "bar",
            "data": vol_white_line_data,
            "xAxisIndex": 2,
            "yAxisIndex": 2,
            "barWidth": 6,
            "barGap": "-100%",
            "z": 10,
            "itemStyle": {"color": "#FFFFFF"},
        },
        {
            "name": "主力啟動線(5)",
            "type": "line",
            "data": clean_list(df["主力啟動線"]),
            "xAxisIndex": 2,
            "yAxisIndex": 2,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFFFF", "width": 1},
        },
        {
            "name": "主力洗盤線(35)",
            "type": "line",
            "data": clean_list(df["主力洗盤線"]),
            "xAxisIndex": 2,
            "yAxisIndex": 2,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFF00", "width": 1},
        },
        {
            "name": "資金異動線(120)",
            "type": "line",
            "data": clean_list(df["資金異動線"]),
            "xAxisIndex": 2,
            "yAxisIndex": 2,
            "showSymbol": False,
            "lineStyle": {"color": "#00FF00", "width": 1},
        },
        # === 副圖三：MACD ===
        {
            "name": "MACD",
            "type": "bar",
            "data": macd_data,
            "xAxisIndex": 3,
            "yAxisIndex": 3,
        },
        {
            "name": "DIF",
            "type": "line",
            "data": clean_list(df["DIF"]),
            "xAxisIndex": 3,
            "yAxisIndex": 3,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFFFF", "width": 1},
        },
        {
            "name": "DEA",
            "type": "line",
            "data": clean_list(df["MACD"]),
            "xAxisIndex": 3,
            "yAxisIndex": 3,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFF00", "width": 1},
        },
        # === 副圖四：莊家控盤 ===
        {
            "name": "莊家控盤",
            "type": "bar",
            "data": zhuang_data,
            "xAxisIndex": 4,
            "yAxisIndex": 4,
        },
        {
            "name": "開始控盤",
            "type": "line",
            "data": kaishi_line_data,
            "xAxisIndex": 4,
            "yAxisIndex": 4,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFF00", "width": 2},
        },
        # === 副圖五：吸拉派落 ===
        {
            "name": "MM",
            "type": "line",
            "data": clean_list(df["MM"]),
            "xAxisIndex": 5,
            "yAxisIndex": 5,
            "showSymbol": False,
            "lineStyle": {"color": "#888888", "width": 1, "type": "dashed"},
        },
        {
            "name": "派",
            "type": "line",
            "data": clean_list(df["派"]),
            "xAxisIndex": 5,
            "yAxisIndex": 5,
            "showSymbol": False,
            "lineStyle": {"color": "#00FF00", "width": 2},
        },
        {
            "name": "落",
            "type": "line",
            "data": clean_list(df["落"]),
            "xAxisIndex": 5,
            "yAxisIndex": 5,
            "showSymbol": False,
            "lineStyle": {"color": "#FFFFFF", "width": 2},
        },
        {
            "name": "吸",
            "type": "line",
            "data": clean_list(df["吸"]),
            "xAxisIndex": 5,
            "yAxisIndex": 5,
            "showSymbol": False,
            "lineStyle": {"color": "#F08080", "width": 2},
        },
        {
            "name": "拉",
            "type": "line",
            "data": clean_list(df["拉"]),
            "xAxisIndex": 5,
            "yAxisIndex": 5,
            "showSymbol": False,
            "lineStyle": {"color": "#FF0000", "width": 2},
        },
    ])

    options = {
        "backgroundColor": "#131722",
        "animation": False,
        "tooltip": {"show": True, "trigger": "axis"},
        "grid": [
            {"left": "4%", "right": "3%", "top": "2%", "height": "30%"},   # 主K
            {"left": "4%", "right": "3%", "top": "34%", "height": "10%"},  # 副圖一
            {"left": "4%", "right": "3%", "top": "46%", "height": "10%"},  # 成交量
            {"left": "4%", "right": "3%", "top": "58%", "height": "10%"},  # MACD
            {"left": "4%", "right": "3%", "top": "70%", "height": "10%"},  # 莊家控盤
            {"left": "4%", "right": "3%", "top": "82%", "height": "10%"},  # 吸拉派落
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
            {"scale": True, "gridIndex": 1, "splitLine": {"show": True, "lineStyle": {"color": "#2A2E39"}}},
            {"scale": True, "gridIndex": 2},
            {"scale": True, "gridIndex": 3},
            {"scale": True, "gridIndex": 4, "splitLine": {"show": True, "lineStyle": {"color": "#2A2E39"}}},
            {"scale": True, "gridIndex": 5, "splitLine": {"show": True, "lineStyle": {"color": "#2A2E39"}}},
        ],
        "dataZoom": [
            {
                "type": "inside",
                "xAxisIndex": [0, 1, 2, 3, 4, 5],
                "start": start_percent,
                "end": 100,
            },
            {
                "type": "slider",
                "xAxisIndex": [0, 1, 2, 3, 4, 5],
                "start": start_percent,
                "end": 100,
                "bottom": "1%",
            },
        ],
        "series": series_list,
    }

    options_json = json.dumps(options)
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
# 5. 主畫面與側邊欄數據綁定 (電腦版 Streamlit 原生介面)
# ---------------------------------------------------------
st.sidebar.title("📈 台股 K 線監控站")

# 原生搜尋列
col_search, col_btn = st.sidebar.columns([3, 1])
with col_search:
    stock_code = st.text_input("輸入股票代碼", value="2330", key="stock_search_input")
with col_btn:
    st.write("") # 對齊用
    st.write("")
    submit_button = st.button("查詢")

input_code = stock_code.strip()

# K 線週期選單
kline_type = st.sidebar.radio(
    "K線週期", ["日K", "週K", "月K", "60分K"], horizontal=True, key="kline_type"
)

# 1. 在即時 API 診斷上方增加「副圖 1 指標切換」下拉選單
sub1_metric = st.sidebar.selectbox(
    "副圖 1 指標切換　波段拐點／資金爆發／六脈神劍／中長期波段",
    ["波段拐點", "資金爆發", "六脈神劍", "中長期波段"],
    key="sub1_metric_select"
)

if input_code:
    stock_name, clean_code, df_daily_raw = fetch_stock_meta_and_kline(input_code)
    realtime = get_realtime_dde(clean_code)

    # 合併即時資料與日 K
    if not df_daily_raw.empty:
        df_daily_raw = (
            df_daily_raw.sort_values("DateStr")
            .drop_duplicates("DateStr", keep="last")
            .reset_index(drop=True)
        )
        df_daily_raw = merge_realtime_to_daily(df_daily_raw, realtime)

    # 抓取 60分K 資料
    df_60 = fetch_60min_kline(clean_code)
    if not df_60.empty:
        df_60 = (
            df_60.sort_values("DateStr")
            .drop_duplicates("DateStr", keep="last")
            .reset_index(drop=True)
        )

    # 計算週期指標（支援 60分K 進行指標計算）
    if kline_type == "日K":
        df = calculate_custom_indicators(df_daily_raw)
    elif kline_type == "週K":
        df_week = resample_kline(df_daily_raw, timeframe="W")
        df = calculate_custom_indicators(df_week)
    elif kline_type == "月K":
        df_month = resample_kline(df_daily_raw, timeframe="M")
        df = calculate_custom_indicators(df_month)
    elif kline_type == "60分K":
        df = calculate_custom_indicators(df_60)

    # ── 即時 API 診斷面板 (側邊欄) ──
    if isinstance(realtime, dict) and "price" in realtime:
        price = realtime.get("price", 0)
        prev_close = realtime.get("prev_close", 0)
        change = price - prev_close if prev_close else 0
        pct_change = (change / prev_close * 100) if prev_close else 0

        if change > 0:
            color = "#FF5252"
            arrow = "▲"
        elif change < 0:
            color = "#00E676"
            arrow = "▼"
        else:
            color = "#CCCCCC"
            arrow = ""

        diag_card_html = f"""
<div style="background-color: #1E222D; border: 1px solid #2A2E39; border-radius: 8px; padding: 12px; margin-bottom: 12px; color: #CCCCCC; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
    <div style="font-size: 14px; font-weight: 600; color: #8E94A2; margin-bottom: 4px;">🔍 即時 API 診斷</div>
    <div style="font-size: 13px; color: #9B9B9B;">{realtime.get('name', '')} ({realtime.get('code', '')})</div>
    <div style="font-size: 24px; font-weight: bold; color: {color}; margin: 2px 0;">{price:,.1f} <span style="font-size: 14px; font-weight: normal; color: #9B9B9B;">元</span></div>
    <div style="font-size: 14px; font-weight: 600; color: {color}; margin-bottom: 10px;">{arrow} {change:+.2f} ({pct_change:+.2f}%)</div>
    <div style="border-top: 1px solid #2A2E39; padding-top: 8px; font-size: 12px; display: grid; grid-template-columns: 1fr 1fr; row-gap: 4px;">
        <div>開盤：<span style="color: #FFFFFF;">{realtime.get('open', 0):,.1f}</span></div>
        <div>最高：<span style="color: #FFFFFF;">{realtime.get('high', 0):,.1f}</span></div>
        <div>最低：<span style="color: #FFFFFF;">{realtime.get('low', 0):,.1f}</span></div>
        <div>昨收：<span style="color: #FFFFFF;">{realtime.get('prev_close', 0):,.1f}</span></div>
        <div>總量：<span style="color: #FFFFFF;">{realtime.get('volume', 0):,} 張</span></div>
        <div>現張：<span style="color: #FFFFFF;">{realtime.get('single_vol', 0)} 張</span></div>
    </div>
</div>
"""
        st.sidebar.markdown(diag_card_html, unsafe_allow_html=True)
    else:
        st.sidebar.write(realtime)

    df_inst = fetch_institutional_data(clean_code)

    table_rows = ""
    for _, row in df_inst.iterrows():
        table_rows += "<tr style='border-bottom: 1px solid #2A2E39;'>"
        table_rows += (
            f"<td style='padding: 6px 2px; color: #CCCCCC;'>{row['日期']}</td>"
        )

        for col in ["外資", "投信", "自營商", "合計"]:
            val = row[col]
            if val > 0:
                color = "#FF3333"
                val_str = f"+{val}"
            elif val < 0:
                color = "#00FF66"
                val_str = str(val)
            else:
                color = "#888888"
                val_str = "0"

            weight = "bold" if col == "合計" else "normal"
            table_rows += f"<td style='padding: 6px 2px; text-align: right; color: {color}; font-weight: {weight};'>{val_str}</td>"
        table_rows += "</tr>"

    # ---------------------------------------------------------
    # 戰情多空共振燈號 (支援日/週/月/60分K)
    # ---------------------------------------------------------
    if kline_type in ["日K", "週K", "月K", "60分K"] and not df.empty and len(df) >= 5:
        latest = df.iloc[-1]

        bull_c1 = latest["Close"] > latest.get("工作線", latest.get("EMA5_60", latest["Close"]))
        bull_c2 = (
            (latest.get("ZYG29", 0) > latest.get("ZYG30", 0))
            or latest.get("HIGH_WIN_BUY", False)
            or latest.get("BASE_GD", False)
        )
        bull_c3 = (latest.get("MACD_Hist", 0) > 0) or (latest.get("DIF", 0) > latest.get("MACD", 0))
        bull_c4 = (latest.get("控盤", 0) > 0) or (latest.get("控盤", 0) > latest.get("控盤_REF", 0))
        bull_c5 = pd.notna(latest.get("KP", 0)) and (latest.get("KP", 0) >= 0)

        bull_score = sum([bull_c1, bull_c2, bull_c3, bull_c4, bull_c5])

        bear_c1 = latest["Close"] < latest.get("MA10", latest["Close"])
        bear_c2 = (latest.get("ZYG29", 0) <= latest.get("ZYG30", 0)) or latest.get(
            "SELL_ALL", False
        )
        bear_c3 = latest.get("DIF", 0) < latest.get("MACD", 0)
        bear_c4 = latest.get("控盤", 0) < 0
        bear_c5 = pd.notna(latest.get("KP", 0)) and (latest.get("KP", 0) < 0)

        bear_score = sum([bear_c1, bear_c2, bear_c3, bear_c5])

        if bull_score == 5:
            light_html = "<span style='color: #FF3333; font-size: 15px;'>🔴 <b>【紅燈：準備數錢 / 買進】</b><br><span style='font-size: 11px; color: #CCCCCC;'>多方條件全面到齊 (5/5)，強烈共振！</span></span>"
            box_border = "#FF3333"
        elif bull_score == 4:
            light_html = "<span style='color: #FF66B2; font-size: 15px;'>🟠 <b>【粉燈：多頭看漲 / 準備】</b><br><span style='font-size: 11px; color: #CCCCCC;'>已集滿 4 項多方條件 (4/5)，偏多看待！</span></span>"
            box_border = "#FF66B2"
        elif bear_score == 5:
            light_html = "<span style='color: #00FF66; font-size: 15px;'>🟢 <b>【綠燈：賣點確立 / 閃人】</b><br><span style='font-size: 11px; color: #CCCCCC;'>空方條件全面到齊 (5/5)，極度危險！</span></span>"
            box_border = "#00FF66"
        elif bear_score == 4:
            light_html = "<span style='color: #FFFF00; font-size: 15px;'>🟡 <b>【黃燈：逐步下跌 / 警戒】</b><br><span style='font-size: 11px; color: #CCCCCC;'>已集滿 4 項空方條件 (4/5), 隨時聽牌轉綠！</span></span>"
            box_border = "#FFFF00"
        else:
            light_html = "<span style='color: #AAAAAA; font-size: 14px;'>⚪ <b>【灰燈：安靜抱股 / 觀望】</b><br><span style='font-size: 11px; color: #888888;'>多空均未達 4 項標準，拉鋸觀望。</span></span>"
            box_border = "#2A2E39"

        st.sidebar.markdown(
            f"""
                <div class="stock-info-card" style="border: 2px solid {box_border}; text-align: center; padding: 10px; margin-bottom: 10px;">
                    <div class="metric-title" style="margin-bottom: 5px;">🚦 戰情多空共振燈號 ({kline_type})</div>
                    <div style="padding: 4px 0;">{light_html}</div>
                </div>
            """,
            unsafe_allow_html=True,
        )

    html_table = f"""
    <div class="stock-info-card" style="padding: 8px 3px; overflow-x: hidden;">
        <div class="metric-title" style="margin-bottom: 8px;">📊 近 7 日三大法人買賣超 (張)</div>
        <table style="width: 100%; font-size: 11px; border-collapse: collapse; font-family: monospace;">
            <thead>
                <tr style="border-bottom: 1px solid #444444; color: #888888; text-align: right;">
                    <th style="text-align: left; padding: 4px 0px; white-space: nowrap;">日期</th>
                    <th style="padding: 4px 0px; white-space: nowrap;">外資</th>
                    <th style="padding: 4px 0px; white-space: nowrap;">投信</th>
                    <th style="padding: 4px 0px; white-space: nowrap;">自營</th>
                    <th style="padding: 4px 0px; white-space: nowrap;">合計</th>
                </tr>
            </thead>
            <tbody>
                {table_rows}
            </tbody>
        </table>
    </div>
    """
    st.sidebar.markdown(html_table, unsafe_allow_html=True)

    # 擴展支援所有週期（包含 60分K）顯示抬頭、實戰風控、莊家控盤與量能主力訊號
    if kline_type in ["日K", "週K", "月K", "60分K"] and not df.empty and len(df) >= 5:
        latest = df.iloc[-1]

        if isinstance(realtime, dict) and realtime.get("prev_close"):
            prev_close = float(realtime["prev_close"])
        else:
            prev_close = df.iloc[-2]["Close"] if len(df) > 1 else latest["Close"]

        change = latest["Close"] - prev_close
        pct_change = (change / prev_close) * 100 if prev_close else 0.0

        p_color = "#FF3333" if change > 0 else ("#00FF66" if change < 0 else "#CCCCCC")
        sign = "+" if change > 0 else ""
        
        # 取得對應均線與控盤數值兼容欄位名稱
        w_line = latest.get("工作線", latest.get("EMA5_60", 0))
        ma10_val = latest.get("MA10", latest.get("MA10_60", 0))
        ma20_val = latest.get("MA20", latest.get("MA20_60", 0))
        ma60_val = latest.get("MA60", latest.get("MA60_60", 0))
        zhuang_val = latest.get("控盤", latest.get("控盤_60", 0))

        pc_header_html = f"""
        <div style="background-color: #1E222D; border: 1px solid #2A2E39; border-radius: 6px; padding: 24px 28px; margin-bottom: 2px;">
            <div style="display: flex; justify-content: flex-start; align-items: center; flex-wrap: nowrap; gap: 20px; white-space: nowrap; overflow: hidden;">
                <!-- 1. 左側：名稱與價格 -->
                <div style="display: flex; align-items: baseline; gap: 10px; flex-shrink: 0;">
                    <span style="font-size: 20px; font-weight: bold; color: #FFFFFF;">{stock_name} ({clean_code})</span>
                    <span style="color: #888888; font-size: 20px;">[{kline_type}]</span>
                    <span style="font-size: 24px; font-weight: bold; color: {p_color}; margin-left: 4px;">
                        {latest['Close']:.2f} <span style="font-size: 16px;">({sign}{change:.2f} / {sign}{pct_change:.2f}%)</span>
                    </span>
                </div>
                <!-- 2. 右側指標 -->
                <div style="display: flex; align-items: center; gap: 16px; font-size: 13px; color: #CCCCCC; flex-shrink: 0;">
                    <div>EMA5: <b style="color:#FFF;">{w_line:.2f}</b></div>
                    <div>MA10: <b style="color:#FFF;">{ma10_val:.2f}</b></div>
                    <div>MA20: <b style="color:#FFF;">{ma20_val:.2f}</b></div>
                    <div>MA60: <b style="color:#FFF;">{ma60_val:.2f}</b></div>
                    <div>成交量: <b style="color:#FFF;">{int(latest['Volume']):,}張</b></div>
                    <div>控盤值: <b style="color:#FFF;">{zhuang_val:.2f}</b></div>
                </div>
            </div>
        </div>
        """
        st.markdown(pc_header_html, unsafe_allow_html=True)

        # 🛡️ 實戰風控卡片
        render_risk_card(df)

        # --- 莊家控盤狀態 ---
        is_high = latest.get("高度控盤", latest.get("高度控盤_60", False))
        is_has = latest.get("有莊控盤", latest.get("有莊控盤_60", False))
        is_out = latest.get("主力出貨", latest.get("主力出貨_60", False))

        if is_high:
            zhuang_status = "高度控盤"
            zhuang_color = "#FF00FF"
        elif is_has:
            zhuang_status = "有莊控盤"
            zhuang_color = "#FF3333"
        elif is_out:
            zhuang_status = "主力出貨"
            zhuang_color = "#00FF00"
        else:
            zhuang_status = "無莊控盤"
            zhuang_color = "#FFFFFF"

        st.sidebar.markdown(
            f"""
                <div class="stock-info-card">
                    <div class="metric-title">🎯 莊家抬轎指標 ({kline_type})</div>
                    <div class="metric-row"><span class="metric-label">控盤值:</span><span class="metric-value">{zhuang_val:.2f}</span></div>
                    <div class="metric-row"><span class="metric-label">當前狀態:</span><span class="metric-value" style="color:{zhuang_color};">{zhuang_status}</span></div>
                </div>
            """,
            unsafe_allow_html=True,
        )

        # --- 量能主力訊號 ---
        vol_ok = latest.get("VOL_OK", latest.get("VOL_OK_60", False))
        vol_attack = latest.get("VOL_出擊", latest.get("VOL_出擊_60", False))
        vol_start = latest.get("VOL_啟動", latest.get("VOL_啟動_60", False))

        if vol_ok:
            vol_sig_text = "暴漲 OK"
            vol_sig_color = "#FF0033"
        elif vol_attack:
            vol_sig_text = "主力出擊"
            vol_sig_color = "#FFFF00"
        elif vol_start:
            vol_sig_text = "低位啟動"
            vol_sig_color = "#00FF00"
        else:
            vol_sig_text = "一般量能"
            vol_sig_color = "#888888"

        v_start_line = latest.get("主力啟動線", latest.get("主力啟動線_60", 0))
        v_wash_line = latest.get("主力洗盤線", latest.get("主力洗盤線_60", 0))
        v_fund_line = latest.get("資金異動線", latest.get("資金異動線_60", 0))

        st.sidebar.markdown(
            f"""
                <div class="stock-info-card">
                    <div class="metric-title">🔥 量能主力訊號 ({kline_type})</div>
                    <div class="metric-row"><span class="metric-label">主力啟動線(5):</span><span class="metric-value">{int(v_start_line):,}</span></div>
                    <div class="metric-row"><span class="metric-label">主力洗盤線(35):</span><span class="metric-value">{int(v_wash_line):,}</span></div>
                    <div class="metric-row"><span class="metric-label">資金異動線(120):</span><span class="metric-value">{int(v_fund_line):,}</span></div>
                    <div class="metric-row"><span class="metric-label">當前量能觸發:</span><span class="metric-value" style="color:{vol_sig_color};">{vol_sig_text}</span></div>
                </div>
            """,
            unsafe_allow_html=True,
        )

        # 根據所選週期渲染對應的 ECharts 圖表
        if kline_type == "60分K":
            if df_60.empty:
                st.error(f"{clean_code} 暫時無法取得 60分鐘K資料")
            else:
                html_60 = render_echarts_html_60(df_60, height=1050, sub1_metric=sub1_metric)
                components.html(html_60, height=1060)
        else:
            render_echarts_html(df, height=1050, sub1_metric=sub1_metric)

    else:
        st.error("查無數據或數據不足，請重新確認股票代號。")