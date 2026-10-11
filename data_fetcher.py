import os
import io
import re
import zipfile
import requests
import pandas as pd
import numpy as np


# =====================================================
# Fugle API 金鑰
# =====================================================
FUGLE_API_KEY = "MWM2YTc1YzItMmE2Zi00ZWYzLWFkNmItODQ0YjFmMzExYTgxIDNjNzZjOGVmLTZhMzMtNDAwMC1hZDY4LWJjOWMwYTU4NmZmMw=="


# =====================================================
# TAIFEX 台指期逐筆成交 API
# =====================================================
TAIFEX_TIME_SALES_URL = (
    "https://openapi.taifex.com.tw/v1/TimeAndSalesData"
)


# =====================================================
# 1. 日 K 線獲取
#    原本 Fugle 流程保留
# =====================================================
def fetch_daily_kline(stock_code):
    """
    抓取日 K 線
    支援個股與加權指數 TAIEX
    """

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

    headers = {
        "X-API-KEY": FUGLE_API_KEY
    }

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

            data = res.json().get(
                "data",
                []
            )

            df = _format_fugle_dataframe(
                data
            )

            if not df.empty:
                return df

    except Exception as e:

        print(
            f"[FUGLE 日K錯誤] "
            f"{target_code}: {e}"
        )

    return pd.DataFrame()


# =====================================================
# 2. 分鐘級 K 線
#
# TX：
#     TAIFEX
#
# 其他個股 / IX0001：
#     原本 Fugle
# =====================================================
def fetch_min_kline(
    stock_code,
    timeframe=5
):

    clean_code = (
        str(stock_code)
        .strip()
        .upper()
        .replace(".TW", "")
        .replace(".TWO", "")
    )

    # -------------------------------------------------
    # TX → TAIFEX（原流程保留）
    # -------------------------------------------------
    if clean_code == "TX":

        return fetch_taifex_tx_kline(
            timeframe=timeframe
        )

    # -------------------------------------------------
    # 股票 / 加權指數 → Fugle
    # -------------------------------------------------
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

    headers = {
        "X-API-KEY": FUGLE_API_KEY
    }

    # 歷史分鐘 K 本機快取：不同股票、不同週期分開保存。
    cache_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data_cache"
    )
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(
        cache_dir,
        f"fugle_min_{target_code}_{timeframe}.csv"
    )

    cached_df = pd.DataFrame()
    if os.path.isfile(cache_path):
        try:
            cached_df = pd.read_csv(
                cache_path,
                dtype={"DateStr": str}
            )
            required_columns = [
                "DateStr", "Open", "High", "Low", "Close", "Volume"
            ]
            if not all(col in cached_df.columns for col in required_columns):
                cached_df = pd.DataFrame()
            else:
                cached_df = cached_df[required_columns].copy()
        except Exception as e:
            print(f"[FUGLE 分K快取讀取失敗] {target_code}: {e}")
            cached_df = pd.DataFrame()

    # -------------------------------------------------
    # A. 更新歷史分鐘 K
    #    第一次下載完整可用歷史；之後從快取最新日期往前回補 7 天，
    #    避免每次切換週期或重新開啟程式都重抓多年資料。
    # -------------------------------------------------
    try:

        url_hist = (
            "https://api.fugle.tw/marketdata/v1.0/"
            f"stock/historical/candles/{target_code}"
        )

        history_rows = []
        range_start = pd.Timestamp("2023-05-23")
        range_end = pd.Timestamp.now().normalize()

        if not cached_df.empty:
            cached_dates = pd.to_datetime(
                cached_df["DateStr"],
                errors="coerce"
            ).dropna()
            if not cached_dates.empty:
                range_start = max(
                    pd.Timestamp("2023-05-23"),
                    cached_dates.max().normalize() - pd.Timedelta(days=7)
                )

        while range_start <= range_end:

            # 每段約 11 個月，確保查詢區間小於一年。
            chunk_end = min(
                range_start + pd.DateOffset(months=11) - pd.Timedelta(days=1),
                range_end
            )

            res_h = requests.get(
                url_hist,
                headers=headers,
                params={
                    "timeframe": str(timeframe),
                    "from": range_start.strftime("%Y-%m-%d"),
                    "to": chunk_end.strftime("%Y-%m-%d")
                },
                timeout=12
            )

            if res_h.status_code == 200:
                history_rows.extend(
                    res_h.json().get("data", [])
                )
            elif res_h.status_code != 404:
                print(
                    f"[FUGLE 歷史分K HTTP錯誤] "
                    f"{target_code} "
                    f"{range_start.strftime('%Y-%m-%d')}~"
                    f"{chunk_end.strftime('%Y-%m-%d')}: "
                    f"HTTP {res_h.status_code}"
                )

            range_start = chunk_end + pd.Timedelta(days=1)

        new_history_df = _format_fugle_dataframe(history_rows)

        if not cached_df.empty or not new_history_df.empty:
            historical_df = pd.concat(
                [cached_df, new_history_df],
                ignore_index=True
            )
            historical_df["DateStr"] = pd.to_datetime(
                historical_df["DateStr"],
                errors="coerce"
            ).dt.strftime("%Y-%m-%d %H:%M:%S")
            historical_df = (
                historical_df
                .dropna(subset=["DateStr"])
                .sort_values("DateStr")
                .drop_duplicates(subset=["DateStr"], keep="last")
                .reset_index(drop=True)
            )
            try:
                historical_df.to_csv(
                    cache_path,
                    index=False,
                    encoding="utf-8-sig"
                )
            except Exception as e:
                print(f"[FUGLE 分K快取寫入失敗] {target_code}: {e}")
        else:
            historical_df = pd.DataFrame()

    except Exception as e:
        print(f"[FUGLE 歷史分K失敗] {target_code}: {e}")
        historical_df = cached_df

    # -------------------------------------------------
    # B. 當日盤中分鐘 K（每次仍抓最新資料）
    # -------------------------------------------------
    live_df = pd.DataFrame()
    try:

        url_live = (
            "https://api.fugle.tw/marketdata/v1.0/"
            f"stock/intraday/candles/{target_code}"
        )

        res_l = requests.get(
            url_live,
            headers=headers,
            params={
                "timeframe": str(timeframe)
            },
            timeout=6
        )

        if res_l.status_code == 200:
            live_df = _format_fugle_dataframe(
                res_l.json().get("data", [])
            )

    except Exception as e:
        print(f"[FUGLE 即時分K失敗] {target_code}: {e}")

    # 歷史快取與即時資料合併；相同時間以即時資料為準。
    frames = [df for df in [historical_df, live_df] if not df.empty]
    if not frames:
        return pd.DataFrame()

    combined_df = pd.concat(frames, ignore_index=True)
    combined_df["DateStr"] = pd.to_datetime(
        combined_df["DateStr"],
        errors="coerce"
    ).dt.strftime("%Y-%m-%d %H:%M:%S")
    return (
        combined_df
        .dropna(subset=["DateStr"])
        .sort_values("DateStr")
        .drop_duplicates(subset=["DateStr"], keep="last")
        .reset_index(drop=True)
    )


def fetch_60min_kline(stock_code):
    """
    抓取 60 分鐘 K 線
    """

    return fetch_min_kline(
        stock_code,
        timeframe=60
    )


# =====================================================
# 3. TAIFEX 數值轉換
# =====================================================
def _taifex_to_float(value):

    try:

        text = (
            str(value)
            .strip()
            .replace(",", "")
        )

        if text in (
            "",
            "-",
            "--",
            "None",
            "nan",
            "NaN"
        ):

            return np.nan

        return float(text)

    except (
        TypeError,
        ValueError
    ):

        return np.nan


# =====================================================
# 4. TAIFEX 時間轉換
# =====================================================
def _taifex_time_text(value):

    text = str(value).strip()

    if not text:
        return ""

    # 已經是 HH:MM:SS
    if ":" in text:
        return text

    # HHMMSS
    # HHMMSSmmm
    digits = "".join(
        ch
        for ch in text
        if ch.isdigit()
    )

    if len(digits) >= 6:

        hh = digits[:2]
        mm = digits[2:4]
        ss = digits[4:6]

        try:

            if (
                int(hh) <= 23
                and int(mm) <= 59
                and int(ss) <= 59
            ):

                return (
                    f"{hh}:{mm}:{ss}"
                )

        except ValueError:
            pass

    return text


# =====================================================
# 5. TAIFEX TX 逐筆成交
# =====================================================
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

    # =================================================
    # 1. 取得 TAIFEX 官方「前30個交易日」下載頁
    # =================================================
    list_url = (
        "https://www.taifex.com.tw/cht/3/"
        "futPrevious30DaysSalesData"
    )

    try:

        response = requests.get(
            list_url,
            headers=headers,
            timeout=20
        )

        response.raise_for_status()

        html = response.text

    except Exception as e:

        print(
            "[TAIFEX] 官方每日逐筆下載頁失敗: "
            f"{e}"
        )

        return pd.DataFrame()

    # =================================================
    # 2. 找出官方 CSV 最新交易日
    # =================================================
    matches = re.findall(
        r"DailydownloadCSV/Daily_(\d{4})_(\d{2})_(\d{2})\.zip",
        html,
        flags=re.IGNORECASE
    )

    if not matches:

        print(
            "[TAIFEX] 官方下載頁找不到 Daily CSV"
        )

        return pd.DataFrame()

    file_dates = sorted(
        {
            f"{y}-{m}-{d}"
            for y, m, d in matches
        }
    )

    trading_date = file_dates[-1]

    zip_url = (
        "https://www.taifex.com.tw/file/taifex/"
        "Dailydownload/DailydownloadCSV/"
        f"Daily_{trading_date.replace('-', '_')}.zip"
    )

    print(
        "[TAIFEX] 官方 TX 交易日："
        f"{trading_date}"
    )

    print(
        "[TAIFEX] 官方 CSV："
        f"Daily_{trading_date.replace('-', '_')}.zip"
    )

    # =================================================
    # 3. 下載官方 Daily CSV ZIP
    # =================================================
    try:

        response = requests.get(
            zip_url,
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

        z = zipfile.ZipFile(
            io.BytesIO(response.content)
        )

        csv_names = [
            name
            for name in z.namelist()
            if name.lower().endswith(".csv")
        ]

        if not csv_names:

            print(
                "[TAIFEX] ZIP 內沒有 CSV"
            )

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

    df.columns = [
        str(col).strip()
        for col in df.columns
    ]

    print(
        f"[TAIFEX] 官方 Daily CSV：{len(df):,} 筆"
    )

    # =================================================
    # 4. 檢查官方 CSV 欄位
    # =================================================
    required = [
        "成交日期",
        "商品代號",
        "到期月份(週別)",
        "成交時間",
        "成交價格",
        "成交數量(B+S)",
    ]

    missing = [
        col
        for col in required
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

    # =================================================
    # 5. 只取 TX
    # =================================================
    product_text = (
        df["商品代號"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    df = df[
        product_text == "TX"
    ].copy()

    if df.empty:

        print(
            "[TAIFEX] 官方 Daily CSV 找不到 TX"
        )

        return pd.DataFrame()

    # =================================================
    # 6. 排除週選 / 價差，只取近月 TX
    # =================================================
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

    df["_contract_month_num"] = (
        pd.to_numeric(
            df["到期月份(週別)"],
            errors="coerce"
        )
    )

    df = df.dropna(
        subset=[
            "_contract_month_num"
        ]
    )

    if df.empty:

        print(
            "[TAIFEX] 找不到可辨識的 TX 契約月份"
        )

        return pd.DataFrame()

    front_month = (
        df["_contract_month_num"]
        .min()
    )

    df = df[
        df["_contract_month_num"] == front_month
    ].copy()

    print(
        "[TAIFEX] TX 近月契約："
        f"{int(front_month)}"
    )

    # =================================================
    # 7. 建立真正成交時間
    # =================================================
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

    df["Volume"] = pd.to_numeric(
        df["成交數量(B+S)"],
        errors="coerce"
    ).fillna(0)

    df = df.dropna(
        subset=[
            "DateTime",
            "TradePrice"
        ]
    ).copy()

    if df.empty:

        print(
            "[TAIFEX] TX 沒有有效成交時間/價格"
        )

        return pd.DataFrame()

    # =================================================
    # 8. 只保留「最新官方交易日」的完整近全交易時段
    #
    # 例如 2026-10-01：
    #   2026-09-30 15:00 ～ 2026-10-01 04:59:59
    #   2026-10-01 08:45 ～ 2026-10-01 13:44:59
    # =================================================
    trading_day = pd.Timestamp(trading_date)
    night_start = trading_day - pd.Timedelta(days=1) + pd.Timedelta(hours=15)
    night_end = trading_day + pd.Timedelta(hours=5)
    day_start = trading_day + pd.Timedelta(hours=8, minutes=45)
    day_end = trading_day + pd.Timedelta(hours=13, minutes=45)

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

    df = df[
        is_night | is_day
    ].copy()

    if df.empty:

        print(
            "[TAIFEX] 最新交易日近全時段沒有 TX 成交資料"
        )

        return pd.DataFrame()

    # =================================================
    # 9. 交易日標記
    #
    # 注意：不修改真正成交時間。
    # 9/30 15:00～10/1 04:59:59
    # 全部屬於 10/1 交易日，但 DateTime 保留原始時間。
    # =================================================
    df["TradingDate"] = trading_date

    # =================================================
    # 10. 依真正成交時間排序
    # =================================================
    df = (
        df[
            [
                "DateTime",
                "TradePrice",
                "Volume",
                "TradingDate"
            ]
        ]
        .sort_values(
            "DateTime"
        )
        .reset_index(
            drop=True
        )
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


# =====================================================
# 6. TAIFEX TX 即時夜盤逐筆成交
#
# 官方 Daily CSV 用來提供完整的「前一夜 + 當日日盤」；
# 盤後 15:00 開始的新夜盤，改由 TAIFEX TimeAndSalesData
# 即時補進來，讓 15:00 之後可以即時形成 K 線。
# =====================================================
def _fetch_taifex_tx_live_night_ticks(trading_date):

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140 Safari/537.36"
        ),
        "Accept": "application/json,text/plain,*/*",
    }

    payload = None

    # 即時夜盤 API 偶爾回應較慢；只在這個即時補資料環節
    # 增加一次重試，不改商品代號、契約月份或 K 線計算。
    for attempt in range(2):
        try:

            response = requests.get(
                TAIFEX_TIME_SALES_URL,
                headers=headers,
                timeout=60
            )

            response.raise_for_status()
            payload = response.json()
            break

        except Exception as e:

            if attempt == 0:
                print(
                    "[TAIFEX] 即時夜盤 TimeAndSalesData 第1次失敗，"
                    "60秒後重新抓取："
                    f"{e}"
                )
            else:
                print(
                    "[TAIFEX] 即時夜盤 TimeAndSalesData 失敗："
                    f"{e}"
                )

    if payload is None:
        return pd.DataFrame()

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get(
            "data",
            payload.get("Data", [])
        )
        if isinstance(rows, dict):
            rows = rows.get(
                "data",
                rows.get("Data", [])
            )
    else:
        rows = []

    if not isinstance(rows, list) or not rows:

        return pd.DataFrame()

    live = pd.DataFrame(rows)
    live.columns = [
        str(col).strip()
        for col in live.columns
    ]

    required = [
        "Date",
        "ProductCode",
        "ContractMonth(Week)",
        "TimeOfTrades",
        "TradePrice",
    ]

    if any(col not in live.columns for col in required):

        print(
            "[TAIFEX] 即時夜盤欄位不足："
            f"{list(live.columns)}"
        )

        return pd.DataFrame()

    live["ProductCode"] = (
        live["ProductCode"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    live = live[
        live["ProductCode"] == "TX"
    ].copy()

    if live.empty:
        return pd.DataFrame()

    month_text = (
        live["ContractMonth(Week)"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    live = live[
        ~month_text.str.contains(
            "W",
            na=False
        )
        &
        ~month_text.str.contains(
            "/",
            na=False
        )
    ].copy()

    live["_month_num"] = pd.to_numeric(
        live["ContractMonth(Week)"],
        errors="coerce"
    )

    live = live.dropna(
        subset=["_month_num"]
    ).copy()

    if live.empty:
        return pd.DataFrame()

    front_month = live["_month_num"].min()

    live = live[
        live["_month_num"] == front_month
    ].copy()

    date_text = (
        live["Date"]
        .astype(str)
        .str.strip()
    )

    time_text = (
        live["TimeOfTrades"]
        .astype(str)
        .str.strip()
    )

    numeric_time = time_text.str.extract(
        r"^(\d{6})(?:\.(\d+))?$",
        expand=True
    )

    mask_numeric = numeric_time[0].notna()

    if mask_numeric.any():

        hh = numeric_time.loc[mask_numeric, 0].str[0:2]
        mm = numeric_time.loc[mask_numeric, 0].str[2:4]
        ss = numeric_time.loc[mask_numeric, 0].str[4:6]
        frac = numeric_time.loc[mask_numeric, 1]

        converted = (
            hh + ":" + mm + ":" + ss
        )

        converted = converted.where(
            frac.isna(),
            converted + "." + frac.fillna("")
        )

        time_text.loc[mask_numeric] = converted

    live["DateTime"] = pd.to_datetime(
        date_text + " " + time_text,
        errors="coerce"
    )

    live["TradePrice"] = pd.to_numeric(
        live["TradePrice"],
        errors="coerce"
    )

    if "Volume(Buy+Sell)" in live.columns:
        live["Volume"] = pd.to_numeric(
            live["Volume(Buy+Sell)"],
            errors="coerce"
        ).fillna(0)
    elif "Volume" in live.columns:
        live["Volume"] = pd.to_numeric(
            live["Volume"],
            errors="coerce"
        ).fillna(0)
    else:
        live["Volume"] = 0

    live = live.dropna(
        subset=[
            "DateTime",
            "TradePrice"
        ]
    ).copy()

    if live.empty:
        return pd.DataFrame()

    trading_day = pd.Timestamp(trading_date)

    # 只補「今天 15:00 開始的新夜盤」。
    # 這一夜屬於下一個一般交易日。
    night_start = (
        trading_day
        + pd.Timedelta(hours=15)
    )

    live = live[
        live["DateTime"] >= night_start
    ].copy()

    if live.empty:
        return pd.DataFrame()

    next_trading_day = (
        trading_day
        + pd.offsets.BDay(1)
    )

    live["TradingDate"] = (
        next_trading_day.strftime("%Y-%m-%d")
    )

    return (
        live[
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


# =====================================================
# 7. TAIFEX TX → 5 / 15 / 30 / 60 分 K
# =====================================================
def fetch_taifex_tx_kline(
    timeframe=5
):

    try:

        timeframe = int(
            timeframe
        )

    except (
        TypeError,
        ValueError
    ):

        print(
            f"[TAIFEX] "
            f"無效 K 線週期: {timeframe}"
        )

        return pd.DataFrame()

    if timeframe not in (
        5,
        15,
        30,
        60
    ):

        print(
            "[TAIFEX] "
            f"不支援的 K 線週期: {timeframe}"
        )

        return pd.DataFrame()

    # -------------------------------------------------
    # 取得 TX 逐筆資料
    # -------------------------------------------------
    ticks = (
        _fetch_taifex_tx_timesales()
    )

    if ticks.empty:

        return pd.DataFrame()

    # -------------------------------------------------
    # 補進今天 15:00 開始的即時夜盤
    # -------------------------------------------------
    official_trading_date = pd.to_datetime(
        ticks["TradingDate"].iloc[0]
    ).strftime("%Y-%m-%d")

    live_night = _fetch_taifex_tx_live_night_ticks(
        official_trading_date
    )

    if not live_night.empty:

        ticks = pd.concat(
            [ticks, live_night],
            ignore_index=True
        )

        ticks = (
            ticks
            .drop_duplicates(
                subset=[
                    "DateTime",
                    "TradePrice",
                    "Volume"
                ],
                keep="last"
            )
            .sort_values("DateTime")
            .reset_index(drop=True)
        )

        print(
            "[TAIFEX] 即時夜盤補入："
            f"{len(live_night):,} 筆 | "
            f"最新：{live_night['DateTime'].iloc[-1]} "
            f"@ {live_night['TradePrice'].iloc[-1]}"
        )

    ticks = (
        ticks
        .set_index(
            "DateTime"
        )
        .sort_index()
    )

    # =================================================
    # 建立 K 線
    # =================================================
    kline = (
        ticks
        .resample(
            f"{timeframe}min"
        )
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

    # -------------------------------------------------
    # 沒成交的時間不建立 K 棒
    # -------------------------------------------------
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
            "[TAIFEX] "
            f"無法建立 {timeframe} 分K"
        )

        return pd.DataFrame()

    # -------------------------------------------------
    # 回復欄位
    # -------------------------------------------------
    kline = (
        kline
        .reset_index()
    )

    # -------------------------------------------------
    # 顯示時間
    # -------------------------------------------------
    kline["DateStr"] = (
        kline["DateTime"]
        .dt.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
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
    ].reset_index(
        drop=True
    )

    # =================================================
    # 顯示 TX 日 / 夜盤資料統計
    # =================================================
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
                    (
                        result_dt.dt.hour < 14
                    )
                    |
                    (
                        (
                            result_dt.dt.hour == 14
                        )
                        &
                        (
                            result_dt.dt.minute <= 0
                        )
                    )
                )
            ).sum()
        )

        night_count = int(
            (
                (
                    result_dt.dt.hour >= 15
                )
                |
                (
                    result_dt.dt.hour < 6
                )
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


# =====================================================
# 7. 盤中即時行情
# =====================================================
def get_realtime_dde(stock_code):

    clean_code = (
        str(stock_code)
        .strip()
        .upper()
        .replace(".TW", "")
        .replace(".TWO", "")
    )

    # -------------------------------------------------
    # 特殊處理：TX (台指期)
    # Fugle API 不支援 TX，改以 TAIFEX K 線資料計算即時價與漲跌
    # -------------------------------------------------
    if clean_code == "TX":
        try:
            df_tx = fetch_taifex_tx_kline(timeframe=5)
            if not df_tx.empty:
                last_price = float(df_tx["Close"].iloc[-1])
                high_price = float(df_tx["High"].max())
                low_price = float(df_tx["Low"].min())
                open_price = float(df_tx["Open"].iloc[0])
                total_vol = int(df_tx["Volume"].sum())

                # 以當日第一根 K 線開盤價作為基準計算漲跌
                prev_close = open_price if open_price > 0 else last_price
                change = last_price - prev_close
                change_pct = (
                    (change / prev_close * 100)
                    if prev_close > 0
                    else 0.0
                )

                return {
                    "code": "TX",
                    "name": "台指期近全",
                    "price": last_price,
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "volume": total_vol,
                    "single_vol": int(df_tx["Volume"].iloc[-1]),
                    "prev_close": prev_close,
                    "change": change,
                    "changePercent": change_pct,
                    "source": "TAIFEX",
                    "last_time": df_tx["DateStr"].iloc[-1],
                }
        except Exception as e:
            print(f"[TX 即時行情計算失敗]: {e}")

    # -------------------------------------------------
    # 原本 Fugle 流程 (一般股票 / 加權指數)
    # -------------------------------------------------
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
                or
                data.get("closePrice")
            )

            if (
                price is not None
                and float(price) > 0
            ):

                return {
                    "code": clean_code,
                    "name": data.get(
                        "name",
                        clean_code
                    ),
                    "price": float(price),
                    "open": float(
                        data.get(
                            "openPrice"
                        )
                        or price
                    ),
                    "high": float(
                        data.get(
                            "highPrice"
                        )
                        or price
                    ),
                    "low": float(
                        data.get(
                            "lowPrice"
                        )
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
                    "change": float(price) - float(
                        data.get(
                            "previousClose"
                        )
                        or 0
                    ),
                    "changePercent": (
                        (
                            float(price) - float(
                                data.get(
                                    "previousClose"
                                )
                                or 0
                            )
                        )
                        / float(
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


# =====================================================
# 8. Fugle 資料格式整理
# =====================================================
def _format_fugle_dataframe(rows):

    if not rows:

        return pd.DataFrame()

    result = []

    for item in rows:

        try:

            result.append({
                "DateStr": str(
                    item.get(
                        "date",
                        ""
                    )
                ).strip(),

                "Open": float(
                    item.get(
                        "open",
                        0
                    )
                ),

                "High": float(
                    item.get(
                        "high",
                        0
                    )
                ),

                "Low": float(
                    item.get(
                        "low",
                        0
                    )
                ),

                "Close": float(
                    item.get(
                        "close",
                        0
                    )
                ),

                "Volume": int(
                    item.get(
                        "volume",
                        0
                    )
                ),
            })

        except Exception:
            pass

    df = pd.DataFrame(
        result
    )

    if df.empty:

        return df

    df["DateStr"] = pd.to_datetime(
        df["DateStr"]
    )

    df = (
        df
        .sort_values(
            "DateStr"
        )
        .drop_duplicates(
            subset=[
                "DateStr"
            ],
            keep="last"
        )
        .reset_index(
            drop=True
        )
    )

    df["DateStr"] = (
        df["DateStr"]
        .dt.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    return df
