# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd


def tdx_ema(series, span):
    return series.ewm(span=span, adjust=False, min_periods=1).mean()


def calculate_swing_indicators(df):
    data = df.copy()

    close = pd.to_numeric(
        data["close"] if "close" in data.columns else data["Close"],
        errors="coerce",
    )
    high = pd.to_numeric(
        data["high"] if "high" in data.columns else data["High"],
        errors="coerce",
    )
    low = pd.to_numeric(
        data["low"] if "low" in data.columns else data["Low"],
        errors="coerce",
    )

    # ==========================================
    # 1. 波段拐點（通達信適中敏感版：參數 8, 8, 4）
    # ==========================================
    gup6 = (2 * close + high + low) / 4.0

    # LLV / HHV 取樣週期：由 13 縮短為 8
    gup7 = low.rolling(window=8, min_periods=1).min()
    gup8 = high.rolling(window=8, min_periods=1).max()

    denom_gup = (gup8 - gup7).replace(0, np.nan).ffill().fillna(1e-6)
    gup9_raw = (gup6 - gup7) / denom_gup * 100.0

    # 第一層 EMA 週期：由 13 縮短為 8
    gup9 = tdx_ema(gup9_raw, 8)

    # REF(GUP9, 2) 對應 Python 的 shift(2)
    ref_gup9_2 = gup9.shift(2).bfill()
    weighted_gup9 = 0.382 * ref_gup9_2 + 0.618 * gup9

    # 第二層 EMA 平滑週期：由 6 縮短為 4
    swing = tdx_ema(weighted_gup9, 4)
    data["波段拐點"] = (swing - 50.0) / 100.0

    # 轉折變色判斷 (對應 IF(波段拐點 > REF(波段拐點, 1)...)
    swing_diff = data["波段拐點"] - data["波段拐點"].shift(1)
    data["波段拐點_紅線"] = data["波段拐點"].where(swing_diff > 0, np.nan)
    data["波段拐點_青線"] = data["波段拐點"].where(swing_diff < 0, np.nan)

    # 2. 中期安全線
    llv60 = low.rolling(window=60, min_periods=1).min()
    hhv60 = high.rolling(window=60, min_periods=1).max()

    denom_price = (hhv60 - llv60).replace(0, np.nan).ffill().fillna(1e-6)
    gup_price = (close - llv60) / denom_price

    ema_gup_price = tdx_ema(gup_price, 3)
    gup1 = ema_gup_price.rolling(window=3, min_periods=1).mean()

    safety = tdx_ema(gup1 - 0.5, 55)
    data["中期安全線"] = safety

    safety_diff = safety - safety.shift(1)
    data["中期安全線_洋紅線"] = safety.where(safety_diff > 0, np.nan)

    return data


def get_explosion_subchart_data(df):
    data = calculate_swing_indicators(df)

    clean = lambda s: [
        None if np.isnan(v) else round(float(v), 4) for v in s
    ]

    series_list = [
        # 波段拐點：黃色底線過渡 + 紅青高亮 (實線)
        {
            "name": "波段拐點(底線)",
            "type": "line",
            "data": clean(data["波段拐點"]),
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "showSymbol": False,
            "smooth": True,
            "lineStyle": {"color": "#FFFF00", "width": 2.5},
        },
        {
            "name": "波段拐點(升)",
            "type": "line",
            "data": clean(data["波段拐點_紅線"]),
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "showSymbol": False,
            "smooth": True,
            "lineStyle": {"color": "#FF0000", "width": 2.5},
        },
        {
            "name": "波段拐點(降)",
            "type": "line",
            "data": clean(data["波段拐點_青線"]),
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "showSymbol": False,
            "smooth": True,
            "lineStyle": {"color": "#00FFFF", "width": 2.5},
        },
        # 中期安全線：灰色底線打底 + 上升段洋紅 (虛線)
        {
            "name": "中期安全線(底線)",
            "type": "line",
            "data": clean(data["中期安全線"]),
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "showSymbol": False,
            "smooth": True,
            "lineStyle": {
                "color": "#888888",
                "width": 1.5,
                "type": "dashed",  # 👈 灰色底線改虛線
            },
        },
        {
            "name": "中期安全線(升)",
            "type": "line",
            "data": clean(data["中期安全線_洋紅線"]),
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "showSymbol": False,
            "smooth": True,
            "lineStyle": {
                "color": "#FF00FF",
                "width": 2.5,
                
            },
        },
    ]

    return series_list