import os
import requests
import pandas as pd
import numpy as np

# Fugle API 金鑰
FUGLE_API_KEY = "MWM2YTc1YzItMmE2Zi00ZWYzLWFkNmItODQ0YjFmMzExYTgxIDNjNzZjOGVmLTZhMzMtNDAwMC1hZDY4LWJjOWMwYTU4NmZmMw=="

# =====================================================
# 1. 日 K 線獲取 (僅保留台股個股與大盤指數)
# =====================================================
def fetch_daily_kline(stock_code):
    """
    抓取日 K 線 (支援個股與加權指數 TAIEX)
    """
    clean_code = str(stock_code).strip().upper().replace(".TW", "").replace(".TWO", "")

    # 加權指數代碼轉換
    target_code = "IX0001" if clean_code in ["TAIEX", "0000", "加權指數", "加權"] else clean_code
    headers = {"X-API-KEY": FUGLE_API_KEY}
    
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{target_code}"
        res = requests.get(url, headers=headers, params={"timeframe": "D"}, timeout=6)
        if res.status_code == 200:
            data = res.json().get("data", [])
            df = _format_fugle_dataframe(data)
            if not df.empty:
                return df
    except Exception as e:
        print(f"[FUGLE 日K錯誤] {target_code}: {e}")

    return pd.DataFrame()

# =====================================================
# 2. 分鐘級 K 線獲取 (5分K / 15分K / 30分K / 60分K)
# =====================================================
def fetch_min_kline(stock_code, timeframe=5):
    """
    通用分鐘級 K 線接口 (歷史 + 盤中即時融合)
    """
    clean_code = str(stock_code).strip().upper().replace(".TW", "").replace(".TWO", "")

    target_code = "IX0001" if clean_code in ["TAIEX", "0000", "加權指數", "加權"] else clean_code
    headers = {"X-API-KEY": FUGLE_API_KEY}
    all_rows = []

    # A. 抓取歷史分鐘 K 線
    try:
        url_hist = f"https://api.fugle.tw/marketdata/v1.0/stock/historical/candles/{target_code}"
        res_h = requests.get(url_hist, headers=headers, params={"timeframe": str(timeframe)}, timeout=6)
        if res_h.status_code == 200:
            all_rows.extend(res_h.json().get("data", []))
    except Exception as e:
        print(f"[FUGLE 歷史分K失敗] {target_code}: {e}")

    # B. 抓取當日盤中即時分鐘 K 線
    try:
        url_live = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/candles/{target_code}"
        res_l = requests.get(url_live, headers=headers, params={"timeframe": str(timeframe)}, timeout=6)
        if res_l.status_code == 200:
            all_rows.extend(res_l.json().get("data", []))
    except Exception as e:
        print(f"[FUGLE 即時分K失敗] {target_code}: {e}")

    return _format_fugle_dataframe(all_rows)


def fetch_60min_kline(stock_code):
    """抓取 60 分鐘 K 線"""
    return fetch_min_kline(stock_code, timeframe=60)

# =====================================================
# 3. 盤中即時行情 (get_realtime_dde)
# =====================================================
def get_realtime_dde(stock_code):
    """
    盤中即時行情
    """
    clean_code = str(stock_code).strip().upper().replace(".TW", "").replace(".TWO", "")
    target_code = "IX0001" if clean_code in ["TAIEX", "0000", "加權指數", "加權"] else clean_code

    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{target_code}"
        res = requests.get(url, headers={"X-API-KEY": FUGLE_API_KEY}, timeout=4)
        if res.status_code == 200:
            data = res.json()
            price = data.get("lastPrice")
            if price is not None and float(price) > 0:
                return {
                    "code": clean_code,
                    "name": data.get("name", clean_code),
                    "price": float(price),
                    "open": float(data.get("openPrice") or price),
                    "high": float(data.get("highPrice") or price),
                    "low": float(data.get("lowPrice") or price),
                    "volume": int(data.get("total", {}).get("tradeVolume", 0)),
                    "single_vol": int(data.get("lastSize") or 0),
                    "prev_close": float(data.get("previousClose") or 0),
                    "source": "Fugle",
                    "last_time": data.get("closeTime"),
                }
    except Exception:
        pass

    return {
        "code": clean_code,
        "name": clean_code,
        "price": 0.0,
        "open": 0.0,
        "high": 0.0,
        "low": 0.0,
        "volume": 0,
        "single_vol": 0,
        "prev_close": 0.0,
        "source": "無",
        "last_time": None,
    }

# =====================================================
# 內部輔助函數
# =====================================================
def _format_fugle_dataframe(rows):
    """資料清洗與時間正序排列"""
    if not rows:
        return pd.DataFrame()

    result = []
    for item in rows:
        try:
            result.append({
                "DateStr": str(item.get("date", "")).strip(),
                "Open": float(item.get("open", 0)),
                "High": float(item.get("high", 0)),
                "Low": float(item.get("low", 0)),
                "Close": float(item.get("close", 0)),
                "Volume": int(item.get("volume", 0)),
            })
        except Exception:
            pass

    df = pd.DataFrame(result)
    if df.empty:
        return df

    # 去重並強制依時間由舊到新排序 (確保 K 線繪製順序正確)
    df["DateStr"] = pd.to_datetime(df["DateStr"])
    df = df.sort_values("DateStr").drop_duplicates(subset=["DateStr"], keep="last").reset_index(drop=True)
    df["DateStr"] = df["DateStr"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return df