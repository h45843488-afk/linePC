import os
import pandas as pd
import numpy as np
import requests
import twstock

def get_huanan_app():
    """試圖連接華南永昌 COM API"""
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        app = win32com.client.Dispatch("JDHNSQuoteOBJ.ApplicationJDHNSQuote")
        app.Init()
        return app
    except Exception:
        return None

def fetch_60min_kline(stock_code):
    """
    Fugle 60分鐘K
    -------------------------------------------------
    ① Historical API：取得歷史60分鐘K
    ② Intraday API：取得今天盤中60分鐘K
    ③ 合併後去除重複時間
    ④ 最後一根保留盤中即時資料
    -------------------------------------------------
    """

    clean_code = (
        str(stock_code)
        .strip()
        .replace(".TW", "")
        .replace(".TWO", "")
    )

    # =====================================================
    # Fugle API 金鑰
    # 保留你原本的金鑰，不要修改
    # =====================================================
    FUGLE_API_KEY = "MWM2YTc1YzItMmE2Zi00ZWYzLWFkNmItODQ0YjFmMzExYTgxIDNjNzZjOGVmLTZhMzMtNDAwMC1hZDY4LWJjOWMwYTU4NmZmMw=="

    headers = {
        "X-API-KEY": FUGLE_API_KEY
    }

    all_rows = []

    # =====================================================
    # ① 歷史 60 分鐘 K
    # =====================================================
    try:

        history_url = (
            "https://api.fugle.tw/"
            "marketdata/v1.0/stock/historical/candles/"
            f"{clean_code}"
        )

        history_params = {
            "timeframe": "60"
        }

        res_history = requests.get(
            history_url,
            headers=headers,
            params=history_params,
            timeout=10
        )

        print(
            f"[FUGLE 60K HIST] {clean_code} "
            f"HTTP={res_history.status_code}"
        )

        if res_history.status_code == 200:

            history_data = res_history.json()

            history_rows = history_data.get(
                "data",
                []
            )

            print(
                f"[FUGLE 60K HIST] {clean_code} "
                f"取得 {len(history_rows)} 根"
            )

            all_rows.extend(history_rows)

        else:

            print(
                f"[FUGLE 60K HIST] "
                f"API錯誤：{res_history.text}"
            )

    except Exception as e:

        print(
            f"[FUGLE 60K HIST錯誤] "
            f"{clean_code}: {e}"
        )

    # =====================================================
    # ② 今天盤中即時 60 分鐘 K
    # =====================================================
    try:

        intraday_url = (
            "https://api.fugle.tw/"
            "marketdata/v1.0/stock/intraday/candles/"
            f"{clean_code}"
        )

        intraday_params = {
            "timeframe": "60"
        }

        res_intraday = requests.get(
            intraday_url,
            headers=headers,
            params=intraday_params,
            timeout=10
        )

        print(
            f"[FUGLE 60K LIVE] {clean_code} "
            f"HTTP={res_intraday.status_code}"
        )

        if res_intraday.status_code == 200:

            intraday_data = res_intraday.json()

            intraday_rows = intraday_data.get(
                "data",
                []
            )

            print(
                f"[FUGLE 60K LIVE] {clean_code} "
                f"取得 {len(intraday_rows)} 根"
            )

            all_rows.extend(intraday_rows)

        else:

            print(
                f"[FUGLE 60K LIVE] "
                f"API錯誤：{res_intraday.text}"
            )

    except Exception as e:

        print(
            f"[FUGLE 60K LIVE錯誤] "
            f"{clean_code}: {e}"
        )

    # =====================================================
    # ③ 完全沒有資料
    # =====================================================
    if not all_rows:

        print(
            f"[FUGLE 60K] {clean_code} "
            f"沒有取得任何60分鐘K"
        )

        return pd.DataFrame()

    # =====================================================
    # ④ 組成 DataFrame
    # =====================================================
    result = []

    for item in all_rows:

        try:

            result.append({
                "DateStr": item.get("date"),

                "Open": float(
                    item.get("open", 0)
                ),

                "High": float(
                    item.get("high", 0)
                ),

                "Low": float(
                    item.get("low", 0)
                ),

                "Close": float(
                    item.get("close", 0)
                ),

                "Volume": int(
                    item.get("volume", 0)
                )
            })

        except Exception as e:

            print(
                f"[FUGLE 60K] "
                f"資料轉換失敗：{e}"
            )

    df = pd.DataFrame(result)

    if df.empty:
        return df

    # =====================================================
    # ⑤ 清理時間
    # =====================================================
    df["DateStr"] = (
        df["DateStr"]
        .astype(str)
        .str.strip()
    )

    # =====================================================
    # ⑥ 排序
    # =====================================================
    df = df.sort_values(
        "DateStr"
    )

    # =====================================================
    # ⑦ 同一根K只保留最後一筆
    #
    # Historical + Intraday 可能有重疊，
    # keep="last" 可以讓今天即時資料覆蓋歷史資料
    # =====================================================
    df = (
        df.drop_duplicates(
            subset=["DateStr"],
            keep="last"
        )
        .reset_index(drop=True)
    )

    # =====================================================
    # ⑧ 最終結果
    # =====================================================
    print(
        f"[FUGLE 60K] {clean_code} "
        f"歷史+即時合併後共 {len(df)} 根60分鐘K"
    )

    if not df.empty:

        print(
            f"[FUGLE 60K] {clean_code} "
            f"第一根={df.iloc[0]['DateStr']} "
            f"最後一根={df.iloc[-1]['DateStr']}"
        )

    return df


def get_realtime_dde(stock_code):
    """
    台股盤中即時行情
    第一來源：Fugle
    第二來源：TWSE
    注意：
    - 絕不使用昨日收盤價當盤中現價
    - 只有取得真正成交價才回傳有效 price
    """

    clean_code = (
        str(stock_code)
        .strip()
        .replace(".TW", "")
        .replace(".TWO", "")
    )

    # =====================================================
    # ① Fugle 即時行情
    # =====================================================
    FUGLE_API_KEY = "MWM2YTc1YzItMmE2Zi00ZWYzLWFkNmItODQ0YjFmMzExYTgxIDNjNzZjOGVmLTZhMzMtNDAwMC1hZDY4LWJjOWMwYTU4NmZmMw=="

    try:
        url = (
            "https://api.fugle.tw/"
            "marketdata/v1.0/stock/intraday/quote/"
            f"{clean_code}"
        )

        headers = {
            "X-API-KEY": FUGLE_API_KEY
        }

        res = requests.get(
            url,
            headers=headers,
            timeout=5
        )

        if res.status_code == 200:
            data = res.json()

            price = data.get("lastPrice")

            # 必須是真正成交價
            if price is not None and float(price) > 0:

                print(
                    f"[FUGLE] {clean_code} "
                    f"最新成交={price} "
                    f"時間={data.get('closeTime')}"
                )

                return {
                    "code": clean_code,
                    "name": data.get("name", clean_code),

                    "price": float(price),

                    "open": float(
                        data.get("openPrice") or 0
                    ),

                    "high": float(
                        data.get("highPrice") or 0
                    ),

                    "low": float(
                        data.get("lowPrice") or 0
                    ),

                    "volume": int(
                        data.get("total", {})
                        .get("tradeVolume", 0)
                    ),

                    "single_vol": int(
                        data.get("lastSize") or 0
                    ),

                    "prev_close": float(
                        data.get("previousClose") or 0
                    ),

                    "source": "Fugle",

                    "last_time": data.get("closeTime")
                }

    except Exception as e:
        print(
            f"[FUGLE] {clean_code} "
            f"即時行情失敗：{e}"
        )

    # =====================================================
    # ② TWSE 備援
    # =====================================================

    try:

        url = (
            "https://mis.twse.com.tw/"
            "stock/api/getStockInfo.jsp"
            f"?ex_ch=tse_{clean_code}.tw"
            f"|otc_{clean_code}.tw"
        )

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://mis.twse.com.tw/"
        }

        res = requests.get(
            url,
            headers=headers,
            timeout=5
        )

        res.raise_for_status()

        data = res.json()

        for info in data.get("msgArray", []):

            if info.get("c") != clean_code:
                continue

            def f(v, default=0.0):
                try:
                    if v in (
                        None,
                        "",
                        "-",
                        "--"
                    ):
                        return default

                    return float(v)

                except Exception:
                    return default

            price = f(info.get("z"))

            # -------------------------------------------------
            # 非常重要：
            # z 沒成交價 = 無法取得即時價格
            # 絕對不能使用 y
            # -------------------------------------------------

            if price <= 0:

                print(
                    f"[TWSE] {clean_code} "
                    f"沒有有效成交價"
                )

                break

            return {
                "code": clean_code,
                "name": info.get(
                    "n",
                    clean_code
                ),

                "price": price,

                "open": f(
                    info.get("o")
                ),

                "high": f(
                    info.get("h")
                ),

                "low": f(
                    info.get("l")
                ),

                "volume": int(
                    f(info.get("v"), 0)
                ),

                "single_vol": 0,

                "prev_close": f(
                    info.get("y")
                ),

                "source": "TWSE",

                "last_time": info.get("t")
            }

    except Exception as e:

        print(
            f"[TWSE] {clean_code} "
            f"即時行情失敗：{e}"
        )

    # =====================================================
    # ③ 全部失敗
    # =====================================================

    print(
        f"[即時行情失敗] "
        f"{clean_code} 沒有取得有效成交價"
    )

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
        "last_time": None
    }
