import os
import io
import re
import zipfile
import requests
import pandas as pd
import numpy as np

FUGLE_API_KEY = "MWM2YTc1YzItMmE2Zi00ZWYzLWFkNmItODQ0YjFmMzExYTgxIDNjNzZjOGVmLTZhMzMtNDAwMC1hZDY4LWJjOWMwYTU4NmZmMw=="

TAIFEX_TIME_SALES_URL = (
    "https://openapi.taifex.com.tw/v1/TimeAndSalesData"
)

TAIFEX_MIS_QUOTE_URL = (
    "https://mis.taifex.com.tw/futures/api/getQuoteList"
)

def fetch_daily_kline(stock_code):
    clean_code = (
        str(stock_code)
        .strip()
        .upper()
        .replace(".TW", "")
        .replace(".TWO", "")
    )
    target_code = (
        "IX0001"
        if clean_code in [
            "TAIEX",
            "0000",
            "加權指數",
            "加權"
        ]
        else clean_code
    )
    headers = {"X-API-KEY": FUGLE_API_KEY}
    try:
        url = (
            "https://api.fugle.tw/marketdata/v1.0/"
            f"stock/historical/candles/{target_code}"
        )
        res = requests.get(
            url,
            headers=headers,
            params={"timeframe": "D"},
            timeout=6
        )
        if res.status_code == 200:
            data = res.json().get("data", [])
            df = _format_fugle_dataframe(data)
            if not df.empty:
                return df
    except Exception as e:
        print(
            f"[FUGLE 日K錯誤] "
            f"{target_code}: {e}"
        )
    return pd.DataFrame()

def fetch_min_kline(stock_code, timeframe=5):
    clean_code = (
        str(stock_code)
        .strip()
        .upper()
        .replace(".TW", "")
        .replace(".TWO", "")
    )
    if clean_code == "TX":
        return fetch_taifex_tx_kline(timeframe=timeframe)
    target_code = (
        "IX0001"
        if clean_code in [
            "TAIEX",
            "0000",
            "加權指數",
            "加權"
        ]
        else clean_code
    )
    headers = {"X-API-KEY": FUGLE_API_KEY}
    all_rows = []
    try:
        url_hist = (
            "https://api.fugle.tw/marketdata/v1.0/"
            f"stock/historical/candles/{target_code}"
        )
        res_h = requests.get(
            url_hist,
            headers=headers,
            params={"timeframe": str(timeframe)},
            timeout=6
        )
        if res_h.status_code == 200:
            all_rows.extend(res_h.json().get("data", []))
    except Exception as e:
        print(
            f"[FUGLE 歷史分K失敗] "
            f"{target_code}: {e}"
        )
    try:
        url_live = (
            "https://api.fugle.tw/marketdata/v1.0/"
            f"stock/intraday/candles/{target_code}"
        )
        res_l = requests.get(
            url_live,
            headers=headers,
            params={"timeframe": str(timeframe)},
            timeout=6
        )
        if res_l.status_code == 200:
            all_rows.extend(res_l.json().get("data", []))
    except Exception as e:
        print(
            f"[FUGLE 即時分K失敗] "
            f"{target_code}: {e}"
        )
    return _format_fugle_dataframe(all_rows)

def fetch_60min_kline(stock_code):
    return fetch_min_kline(stock_code, timeframe=60)

def _taifex_to_float(value):
    try:
        text = str(value).strip().replace(",", "")
        if text in ("", "-", "--", "None", "nan", "NaN"):
            return np.nan
        return float(text)
    except (TypeError, ValueError):
        return np.nan

def _taifex_time_text(value):
    text = str(value).strip()
    if not text:
        return ""
    if ":" in text:
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 6:
        hh = digits[:2]
        mm = digits[2:4]
        ss = digits[4:6]
        try:
            if int(hh) <= 23 and int(mm) <= 59 and int(ss) <= 59:
                return f"{hh}:{mm}:{ss}"
        except ValueError:
            pass
    return text

def _fetch_taifex_tx_timesales():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/140 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/json,*/*",
    }
    list_url = (
        "https://www.taifex.com.tw/cht/3/"
        "futPrevious30DaysSalesData"
    )
    try:
        response = requests.get(list_url, headers=headers, timeout=20)
        response.raise_for_status()
        html = response.text
    except Exception as e:
        print(
            "[TAIFEX] 官方每日逐筆下載頁失敗: "
            f"{e}"
        )
        return pd.DataFrame()
    matches = re.findall(
        r"DailydownloadCSV/Daily_(\d{4})_(\d{2})_(\d{2})\.zip",
        html,
        flags=re.IGNORECASE
    )
    if not matches:
        print("[TAIFEX] 官方下載頁找不到 Daily CSV")
        return pd.DataFrame()
    file_dates = sorted({f"{y}-{m}-{d}" for y, m, d in matches})
    trading_date = file_dates[-1]
    zip_url = (
        "https://www.taifex.com.tw/file/taifex/"
        "Dailydownload/DailydownloadCSV/"
        f"Daily_{trading_date.replace('-', '_')}.zip"
    )
    print("[TAIFEX] 官方 TX 交易日：" f"{trading_date}")
    print(
        "[TAIFEX] 官方 CSV："
        f"Daily_{trading_date.replace('-', '_')}.zip"
    )
    try:
        response = requests.get(zip_url, headers=headers, timeout=30)
        response.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(response.content))
        csv_names = [
            name for name in z.namelist()
            if name.lower().endswith(".csv")
        ]
        if not csv_names:
            print("[TAIFEX] ZIP 內沒有 CSV")
            return pd.DataFrame()
        csv_name = csv_names[0]
        with z.open(csv_name) as f:
            df = pd.read_csv(
                f,
                encoding="cp950",
                low_memory=False
            )
    except Exception as e:
        print(
            "[TAIFEX] 官方 Daily CSV 下載/解析失敗: "
            f"{e}"
        )
        return pd.DataFrame()

    df.columns = [str(col).strip() for col in df.columns]
    print(f"[TAIFEX] 官方 Daily CSV：{len(df):,} 筆")

    required = [
        "成交日期",
        "商品代號",
        "到期月份(週別)",
        "成交時間",
        "成交價格",
        "成交數量(B+S)",
    ]
    missing = [
        col for col in required
        if col not in df.columns
    ]
    if missing:
        print(
            "[TAIFEX] 官方 CSV 欄位不足："
            f"{', '.join(missing)}"
        )
        print(
            "[TAIFEX] 實際欄位："
            f"{list(df.columns)}"
        )
        return pd.DataFrame()

    product_text = (
        df["商品代號"]
        .astype(str)
        .str.strip()
        .str.upper()
    )
    df = df[product_text == "TX"].copy()

    if df.empty:
        print("[TAIFEX] 官方 Daily CSV 找不到 TX")
        return pd.DataFrame()

    month_text = (
        df["到期月份(週別)"]
        .astype(str)
        .str.strip()
    )
    df = df[
        ~month_text.str.contains(
            "W",
            case=False,
            na=False
        )
        &
        ~month_text.str.contains(
            "/",
            na=False
        )
    ].copy()

    df["_contract_month_num"] = pd.to_numeric(
        df["到期月份(週別)"],
        errors="coerce"
    )
    df = df.dropna(
        subset=["_contract_month_num"]
    )

    if df.empty:
        print("[TAIFEX] 找不到可辨識的 TX 契約月份")
        return pd.DataFrame()

    front_month = df["_contract_month_num"].min()
    df = df[
        df["_contract_month_num"] == front_month
    ].copy()

    print(
        "[TAIFEX] TX 近月契約："
        f"{int(front_month)}"
    )

    date_text = (
        df["成交日期"]
        .astype(str)
        .str.strip()
    )
    time_text = (
        df["成交時間"]
        .astype(str)
        .str.strip()
        .str.zfill(6)
    )

    df["DateTime"] = pd.to_datetime(
        date_text + " " + time_text,
        format="%Y%m%d %H%M%S",
        errors="coerce"
    )

    df["TradePrice"] = pd.to_numeric(
        df["成交價格"],
        errors="coerce"
    )
    df["Volume"] = (
        pd.to_numeric(
            df["成交數量(B+S)"],
            errors="coerce"
        )
        .fillna(0)
    )

    df = df.dropna(
        subset=["DateTime", "TradePrice"]
    ).copy()

    if df.empty:
        print(
            "[TAIFEX] TX 沒有有效成交時間/價格"
        )
        return pd.DataFrame()

    trading_day = pd.Timestamp(trading_date)

    night_start = (
        trading_day
        - pd.Timedelta(days=1)
        + pd.Timedelta(hours=15)
    )
    night_end = (
        trading_day
        + pd.Timedelta(hours=5)
    )
    day_start = (
        trading_day
        + pd.Timedelta(hours=8, minutes=45)
    )
    day_end = (
        trading_day
        + pd.Timedelta(hours=13, minutes=45)
    )

    is_night = (
        (df["DateTime"] >= night_start)
        &
        (df["DateTime"] < night_end)
    )

    is_day = (
        (df["DateTime"] >= day_start)
        &
        (df["DateTime"] < day_end)
    )

    df = df[is_night | is_day].copy()

    if df.empty:
        print(
            "[TAIFEX] 最新交易日近全時段沒有 TX 成交資料"
        )
        return pd.DataFrame()

    df["TradingDate"] = trading_day

    df = (
        df[
            [
                "DateTime",
                "TradePrice",
                "Volume",
                "TradingDate"
            ]
        ]
        .sort_values("DateTime")
        .reset_index(drop=True)
    )

    print(
        "[TAIFEX] 近全逐筆資料："
        f"{len(df):,} 筆"
    )
    print(
        "[TAIFEX] 夜盤："
        f"{int(is_night.sum()):,} 筆 | "
        "日盤："
        f"{int(is_day.sum()):,} 筆"
    )
    print(
        "[TAIFEX] 最早成交："
        f"{df['DateTime'].iloc[0]}"
    )
    print(
        "[TAIFEX] 最後成交："
        f"{df['DateTime'].iloc[-1]}"
    )

    return df

def fetch_taifex_tx_kline(timeframe=5):
    try:
        timeframe = int(timeframe)
    except (TypeError, ValueError):
        print(
            f"[TAIFEX] 無效 K 線週期: {timeframe}"
        )
        return pd.DataFrame()

    if timeframe not in (5, 15, 30, 60):
        print(
            f"[TAIFEX] 不支援的 K 線週期: {timeframe}"
        )
        return pd.DataFrame()

    ticks = _fetch_taifex_tx_timesales()

    if ticks.empty:
        return pd.DataFrame()

    ticks = (
        ticks
        .set_index("DateTime")
        .sort_index()
    )

    kline = (
        ticks
        .resample(f"{timeframe}min")
        .agg({
            "TradePrice": [
                "first",
                "max",
                "min",
                "last"
            ],
            "Volume": "sum"
        })
    )

    kline.columns = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume"
    ]

    kline = kline.dropna(
        subset=[
            "Open",
            "High",
            "Low",
            "Close"
        ]
    )

    if kline.empty:
        print(
            f"[TAIFEX] 無法建立 {timeframe} 分K"
        )
        return pd.DataFrame()

    kline = kline.reset_index()

    kline["DateStr"] = (
        kline["DateTime"]
        .dt.strftime("%Y-%m-%d %H:%M:%S")
    )

    kline["Volume"] = (
        pd.to_numeric(
            kline["Volume"],
            errors="coerce"
        )
        .fillna(0)
        .astype(int)
    )

    result = kline[
        [
            "DateStr",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume"
        ]
    ].reset_index(drop=True)

    if not result.empty:
        result_dt = pd.to_datetime(
            result["DateStr"],
            errors="coerce"
        )

        day_count = int(
            (
                (result_dt.dt.hour >= 8)
                &
                (
                    (result_dt.dt.hour < 14)
                    |
                    (
                        (result_dt.dt.hour == 14)
                        &
                        (result_dt.dt.minute <= 0)
                    )
                )
            ).sum()
        )

        night_count = int(
            (
                (result_dt.dt.hour >= 15)
                |
                (result_dt.dt.hour < 6)
            ).sum()
        )

        print(
            f"[TAIFEX] TX {timeframe}分K 建立完成："
            f"{len(result):,} 根"
        )
        print(
            f"[TAIFEX] 日盤 K：{day_count:,} 根 | "
            f"夜盤 K：{night_count:,} 根"
        )
        print(
            "[TAIFEX] 最早："
            f"{result['DateStr'].iloc[0]}"
        )
        print(
            "[TAIFEX] 最後："
            f"{result['DateStr'].iloc[-1]}"
        )

    return result

def get_realtime_dde(stock_code):
    clean_code = (
        str(stock_code)
        .strip()
        .upper()
        .replace(".TW", "")
        .replace(".TWO", "")
    )

    if clean_code == "TX":
        try:
            mis_headers = {
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140 Safari/537.36"
                ),
                "Referer": (
                    "https://mis.taifex.com.tw/futures/"
                ),
                "Accept": (
                    "application/json, text/plain, */*"
                ),
            }

            mis_body = {
                "MarketID": "0",
                "SymbolID": [
                    "TX-F",
                    "TX-M"
                ]
            }

            mis_res = requests.post(
                TAIFEX_MIS_QUOTE_URL,
                headers=mis_headers,
                json=mis_body,
                timeout=6
            )

            mis_res.raise_for_status()

            mis_data = mis_res.json()

            # TAIFEX MIS 實際回傳欄位名稱為 RtData
            quote_list = (
                mis_data.get("RtData", {})
                .get("QuoteList", [])
            )

            front_quotes = []

            for quote in quote_list:
                symbol_id = str(
                    quote.get("SymbolID", "")
                ).strip().upper()

                if re.fullmatch(
                    r"TXF[A-Z]\d+-F",
                    symbol_id
                ):
                    front_quotes.append(quote)

            if front_quotes:
                # 按實際合約年月選擇近月 TX
                month_map = {
                    "A": 1, "B": 2, "C": 3, "D": 4,
                    "E": 5, "F": 6, "G": 7, "H": 8,
                    "I": 9, "J": 10, "K": 11, "L": 12
                }

                def contract_key(q):
                    symbol = str(q.get("SymbolID", ""))
                    m = re.fullmatch(r"TXF([A-L])(\d)-F", symbol)
                    if not m:
                        return (9999, 99)
                    month = month_map[m.group(1)]
                    year_digit = int(m.group(2))
                    return (year_digit, month)

                front_quotes = sorted(
                    front_quotes,
                    key=contract_key
                )
                quote = front_quotes[0]

                symbol_id = str(
                    quote.get("SymbolID", "TX")
                ).strip()

                price = _taifex_to_float(
                    quote.get("CLastPrice")
                )
                open_price = _taifex_to_float(
                    quote.get("COpenPrice")
                )
                high_price = _taifex_to_float(
                    quote.get("CHighPrice")
                )
                low_price = _taifex_to_float(
                    quote.get("CLowPrice")
                )
                total_volume = _taifex_to_float(
                    quote.get("CTotalVolume")
                )
                prev_close = _taifex_to_float(
                    quote.get("CRefPrice")
                )
                change = _taifex_to_float(
                    quote.get("CDiff")
                )
                change_pct = _taifex_to_float(
                    quote.get("CDiffRate")
                )

                cdate = str(
                    quote.get("CDate", "")
                ).strip()

                ctime = str(
                    quote.get("CTime", "")
                ).strip()

                if pd.notna(price) and price > 0:
                    return {
                        "code": "TX",
                        "name": "台指期近全",
                        "price": float(price),
                        "open": (
                            float(open_price)
                            if pd.notna(open_price)
                            else float(price)
                        ),
                        "high": (
                            float(high_price)
                            if pd.notna(high_price)
                            else float(price)
                        ),
                        "low": (
                            float(low_price)
                            if pd.notna(low_price)
                            else float(price)
                        ),
                        "volume": (
                            int(total_volume)
                            if pd.notna(total_volume)
                            else 0
                        ),
                        "single_vol": 0,
                        "prev_close": (
                            float(prev_close)
                            if pd.notna(prev_close)
                            else 0.0
                        ),
                        "change": (
                            float(change)
                            if pd.notna(change)
                            else 0.0
                        ),
                        "changePercent": (
                            float(change_pct)
                            if pd.notna(change_pct)
                            else 0.0
                        ),
                        "source": "TAIFEX MIS",
                        "last_time": (
                            f"{cdate} {ctime}"
                            if cdate and ctime
                            else None
                        ),
                        "symbol_id": symbol_id,
                    }

            print(
                "[TX MIS 即時行情] "
                "找不到 TX 日盤近月合約"
            )

        except Exception as e:
            print(
                f"[TX MIS 即時行情失敗]: {e}"
            )

    target_code = (
        "IX0001"
        if clean_code in [
            "TAIEX",
            "0000",
            "加權指數",
            "加權"
        ]
        else clean_code
    )

    try:
        url = (
            "https://api.fugle.tw/marketdata/v1.0/"
            f"stock/intraday/quote/{target_code}"
        )

        res = requests.get(
            url,
            headers={
                "X-API-KEY": FUGLE_API_KEY
            },
            timeout=4
        )

        if res.status_code == 200:
            data = res.json()

            price = (
                data.get("lastPrice")
                or data.get("closePrice")
            )

            if price is not None and float(price) > 0:
                return {
                    "code": clean_code,
                    "name": data.get(
                        "name",
                        clean_code
                    ),
                    "price": float(price),
                    "open": float(
                        data.get("openPrice")
                        or price
                    ),
                    "high": float(
                        data.get("highPrice")
                        or price
                    ),
                    "low": float(
                        data.get("lowPrice")
                        or price
                    ),
                    "volume": int(
                        data.get(
                            "total",
                            {}
                        ).get(
                            "tradeVolume",
                            0
                        )
                    ),
                    "single_vol": int(
                        data.get(
                            "lastSize"
                        )
                        or 0
                    ),
                    "prev_close": float(
                        data.get(
                            "previousClose"
                        )
                        or 0
                    ),
                    "change": (
                        float(price)
                        - float(
                            data.get(
                                "previousClose"
                            )
                            or 0
                        )
                    ),
                    "changePercent": (
                        (
                            float(price)
                            - float(
                                data.get(
                                    "previousClose"
                                )
                                or 0
                            )
                        )
                        /
                        float(
                            data.get(
                                "previousClose"
                            )
                            or 1
                        )
                        * 100
                    ),
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
        "change": 0.0,
        "changePercent": 0.0,
        "source": "無",
        "last_time": None,
    }

def _format_fugle_dataframe(rows):
    if not rows:
        return pd.DataFrame()

    result = []

    for item in rows:
        try:
            result.append({
                "DateStr": str(
                    item.get("date", "")
                ).strip(),
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
                ),
            })
        except Exception:
            pass

    df = pd.DataFrame(result)

    if df.empty:
        return df

    df["DateStr"] = pd.to_datetime(
        df["DateStr"]
    )

    df = (
        df
        .sort_values("DateStr")
        .drop_duplicates(
            subset=["DateStr"],
            keep="last"
        )
        .reset_index(drop=True)
    )

    df["DateStr"] = (
        df["DateStr"]
        .dt.strftime("%Y-%m-%d %H:%M:%S")
    )

    return df
