import numpy as np
import pandas as pd


def tdx_sma(series: pd.Series, n: int, m: int) -> pd.Series:
    """模擬通達信的 SMA(C, N, M) 權重移動平均"""
    alpha = m / n
    return series.ewm(alpha=alpha, adjust=False).mean()


def get_subchart_data(df: pd.DataFrame, metric_name: str = "主力資金"):
    if df.empty or len(df) < 10:
        return []

    data = df.copy()

    # =========================================================
    # 分支 1：六脈神劍 (6 層指標紅綠箭頭 + 起爆日白柱/買點)
    # =========================================================
    if metric_name == "六脈神劍":
        if "ABC1" not in data.columns:
            import custom_indicator

            data = custom_indicator.tdx_resonance_strategy(data)

        n = len(data)

        # 1. 提取 6 個指標的布林狀態
        c1 = (
            data["ABC1"].astype(bool)
            if "ABC1" in data.columns
            else pd.Series([False] * n, index=data.index)
        )
        c2 = (
            data["ABC2"].astype(bool)
            if "ABC2" in data.columns
            else pd.Series([False] * n, index=data.index)
        )
        c3 = (
            data["ABC3"].astype(bool)
            if "ABC3" in data.columns
            else pd.Series([False] * n, index=data.index)
        )
        c4 = (
            data["ABC4"].astype(bool)
            if "ABC4" in data.columns
            else pd.Series([False] * n, index=data.index)
        )
        c5 = (
            data["ABC5"].astype(bool)
            if "ABC5" in data.columns
            else pd.Series([False] * n, index=data.index)
        )
        c6 = (
            data["ABC6"].astype(bool)
            if "ABC6" in data.columns
            else pd.Series([False] * n, index=data.index)
        )

        # 2. 判斷今天是否 6 個指標全部為紅色向上
        all_gold_today = c1 & c2 & c3 & c4 & c5 & c6

        # 3. 只在「六紅第一次同時出現」的那一天畫白柱
        first_gold_bar = all_gold_today & (~all_gold_today.shift(1, fill_value=False))

        # 4. 白柱與買點
        bar_white = [100 if b else 0 for b in first_gold_bar]
        sig_buy = [100 if b else None for b in first_gold_bar]

        # 定義 6 個指標對應的 Y 軸高度與名稱
        levels = [
            ("ABC1", 15, "MACD"),
            ("ABC2", 30, "KDJ"),
            ("ABC3", 45, "RSI"),
            ("ABC4", 60, "LWR"),
            ("ABC5", 75, "BBI"),
            ("ABC6", 90, "ZLMM"),
        ]

        # 收集 6 層指標的紅箭頭(多)與綠箭頭(空)
        red_data = {level_name: [None] * n for _, _, level_name in levels}
        green_data = {level_name: [None] * n for _, _, level_name in levels}

        for i in range(n):
            for col, y_val, level_name in levels:
                val = data[col].iloc[i] if col in data.columns else False
                if val:
                    red_data[level_name][i] = y_val
                else:
                    green_data[level_name][i] = y_val

        # 構建 ECharts 基礎 Series
        series_list = [
            {
                "name": "六脈起爆點",
                "type": "bar",
                "data": bar_white,
                "xAxisIndex": 1,
                "yAxisIndex": 1,
                "barWidth": "12%",
                "itemStyle": {"color": "#FFFFFF", "opacity": 0.85},
            },
            {
                "name": "★買",
                "type": "scatter",
                "data": sig_buy,
                "xAxisIndex": 1,
                "yAxisIndex": 1,
                "symbol": "circle",
                "symbolSize": 18,
                "itemStyle": {"color": "#FF0000"},
                "label": {
                    "show": True,
                    "formatter": "買",
                    "color": "#FFFFFF",
                    "fontSize": 11,
                    "fontWeight": "bold",
                },
            },
        ]

        arrow_path = "path://M12 2L4.5 20.29l.71.71L12 18l6.79 3 .71-.71z"
        for _, _, level_name in levels:
            series_list.append({
                "name": f"{level_name}_多",
                "type": "scatter",
                "data": red_data[level_name],
                "xAxisIndex": 1,
                "yAxisIndex": 1,
                "symbol": arrow_path,
                "symbolSize": 9,
                "itemStyle": {"color": "#FF2222"},
            })
            series_list.append({
                "name": f"{level_name}_空",
                "type": "scatter",
                "data": green_data[level_name],
                "xAxisIndex": 1,
                "yAxisIndex": 1,
                "symbol": arrow_path,
                "symbolRotate": 180,
                "symbolSize": 9,
                "itemStyle": {"color": "#00FF00"},
            })

        return series_list

    # =========================================================
    # 分支 2：預設主力資金 (資金爆發) 繪圖邏輯
    # =========================================================
    close = data["close"] if "close" in data.columns else data["Close"]
    high = data["high"] if "high" in data.columns else data["High"]
    low = data["low"] if "low" in data.columns else data["Low"]
    open_p = data["open"] if "open" in data.columns else data["Open"]
    vol = data["volume"] if "volume" in data.columns else data["Volume"]

    # 1. 計算主力資金
    llv_34 = low.rolling(window=34).min()
    hhv_34 = high.rolling(window=34).max()
    rsv = 100 * (close - llv_34) / (hhv_34 - llv_34 + 1e-9)
    data["主力資金"] = rsv.ewm(span=3, adjust=False).mean()
    fund = data["主力資金"]
    n = len(data)

    # 2. 原汁原味主力進場 / 洗盤吸籌柱 (VAR1 ~ VAR5)
    data["ZL_VAR1"] = ((low + open_p + close + high) / 4).shift(1)
    zl_diff = low - data["ZL_VAR1"]

    zl_sma1 = tdx_sma(zl_diff.abs(), 13, 1)
    zl_positive = zl_diff.clip(lower=0)
    zl_sma2 = tdx_sma(zl_positive, 10, 1)

    data["ZL_VAR2"] = (
        (zl_sma1 / zl_sma2.replace(0, np.nan))
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0)
    )
    data["ZL_VAR3"] = data["ZL_VAR2"].ewm(span=10, adjust=False).mean()
    data["ZL_VAR4"] = low.rolling(window=33, min_periods=1).min()

    zl_condition = np.where(low <= data["ZL_VAR4"], data["ZL_VAR3"], 0)
    data["ZL_VAR5"] = (
        pd.Series(zl_condition, index=data.index, dtype="float64")
        .ewm(span=3, adjust=False)
        .mean()
    )

    var5_scaled = data["ZL_VAR5"] * 25

    bar_magenta = []
    bar_green = []
    for i in range(n):
        val = var5_scaled.iloc[i]
        prev_val = var5_scaled.iloc[i - 1] if i > 0 else 0
        if pd.notna(val) and val > 0:
            if i == 0 or val >= prev_val:
                bar_magenta.append(round(float(val), 2))
                bar_green.append(0)
            else:
                bar_magenta.append(0)
                bar_green.append(round(float(val), 2))
        else:
            bar_magenta.append(0)
            bar_green.append(0)

    # 3. 大資金進場選股指標（主力資金模式的白柱）
    var1_h = low.shift(1)
    diff_h = (low - var1_h).abs()
    pos_diff_h = (low - var1_h).clip(lower=0)
    sma_abs_h = tdx_sma(diff_h, 13, 1)
    sma_max_h = tdx_sma(pos_diff_h, 13, 1)
    var2h = (sma_abs_h / sma_max_h.replace(0, np.nan)) * 4
    var3h = var2h.ewm(span=13, adjust=False).mean()
    var4h = low.rolling(window=34, min_periods=1).min()
    var5_cond_h = np.where(low <= var4h, var3h, 0)
    var5h = (
        pd.Series(var5_cond_h, index=data.index)
        .ewm(span=3, adjust=False)
        .mean()
    )

    llv_75 = low.rolling(window=75, min_periods=1).min()
    hhv_75 = high.rolling(window=75, min_periods=1).max()
    rsv_close = 100 * (close - llv_75) / (hhv_75 - llv_75 + 1e-9)
    rsv_open = 100 * (open_p - llv_75) / (hhv_75 - llv_75 + 1e-9)

    sma_rsv_c1 = tdx_sma(rsv_close, 20, 1)
    sma_rsv_c2 = tdx_sma(sma_rsv_c1, 15, 1)
    var6h = 100 - 3 * sma_rsv_c1 + 2 * sma_rsv_c2

    sma_rsv_o1 = tdx_sma(rsv_open, 20, 1)
    sma_rsv_o2 = tdx_sma(sma_rsv_o1, 15, 1)
    var7h = 100 - 3 * sma_rsv_o1 + 2 * sma_rsv_o2

    var8h = (
        (var6h < var7h.shift(1)) & (vol > vol.shift(1)) & (close > close.shift(1))
    )
    signal_count = var8h.astype(int).rolling(window=18, min_periods=1).sum()
    big_money_raw = var8h & (signal_count == 1)

    # 這裡同樣加入防重複機制：確保大資金白柱只在觸發第一天顯示
    first_big_money = big_money_raw & (~big_money_raw.shift(1).fillna(False))
    bar_white = [85 if val else 0 for val in first_big_money]

    # 4. ZIG 階梯多空趨勢線
    direction = [85] * n
    curr_dir = 85
    last_pivot = close.iloc[0]
    zig_pct = 0.05

    for i in range(1, n):
        c = close.iloc[i]
        if curr_dir == 85:
            if c < last_pivot:
                last_pivot = c
            elif c >= last_pivot * (1 + zig_pct):
                curr_dir = 15
                last_pivot = c
        else:
            if c > last_pivot:
                last_pivot = c
            elif c <= last_pivot * (1 - zig_pct):
                curr_dir = 85
                last_pivot = c
        direction[i] = curr_dir

    main_fund = [round(float(x), 2) if pd.notna(x) else 0 for x in fund]
    dir_line = [float(x) for x in direction]

    line_20, line_50, line_65, line_80 = (
        [20] * n,
        [50] * n,
        [65] * n,
        [80] * n,
    )

    sig_chao, sig_jia_50, sig_jia_65, sig_bao, sig_kong = (
        [None] * n,
        [None] * n,
        [None] * n,
        [None] * n,
        [None] * n,
    )
    cooldown, last_chao, last_jia, last_bao, last_kong = 8, -99, -99, -99, -99

    for i in range(1, n):
        f_curr, f_prev = fund.iloc[i], fund.iloc[i - 1]
        if pd.isna(f_curr) or pd.isna(f_prev):
            continue

        if f_prev < 20 and f_curr >= 20 and (i - last_chao > cooldown):
            sig_chao[i] = main_fund[i]
            last_chao = i
        if f_prev < 50 and f_curr >= 50 and (i - last_jia > cooldown):
            sig_jia_50[i] = main_fund[i]
            last_jia = i
        if f_prev < 65 and f_curr >= 65 and (i - last_jia > cooldown):
            sig_jia_65[i] = main_fund[i]
            last_jia = i
        if f_prev < 80 and f_curr >= 80 and (i - last_bao > cooldown):
            sig_bao[i] = main_fund[i]
            last_bao = i
        if f_prev > 80 and f_curr <= 80 and (i - last_kong > cooldown):
            sig_kong[i] = main_fund[i]
            last_kong = i

    series_list = [
        {
            "name": "大資金進場",
            "type": "bar",
            "data": bar_white,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "itemStyle": {"color": "#FFFFFF", "opacity": 0.85},
        },
        {
            "name": "主力進場",
            "type": "bar",
            "data": bar_magenta,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "itemStyle": {
                "color": "rgba(0,0,0,0)",
                "borderColor": "#FF00FF",
                "borderWidth": 1.5,
            },
        },
        {
            "name": "洗盤",
            "type": "bar",
            "data": bar_green,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "itemStyle": {
                "color": "rgba(0,0,0,0)",
                "borderColor": "#00FF00",
                "borderWidth": 1.5,
            },
        },
        {
            "name": "主力資金",
            "type": "line",
            "data": main_fund,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "smooth": True,
            "showSymbol": False,
            "lineStyle": {"width": 2, "color": "#FF0000"},
        },
        {
            "name": "多空方向",
            "type": "line",
            "data": dir_line,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "step": "start",
            "showSymbol": False,
            "lineStyle": {"width": 2, "color": "#FFFF00"},
        },
        {
            "name": "20抄底線",
            "type": "line",
            "data": line_20,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "showSymbol": False,
            "lineStyle": {"width": 1, "color": "#FFFFFF"},
        },
        {
            "name": "50警戒線",
            "type": "line",
            "data": line_50,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "showSymbol": False,
            "lineStyle": {"width": 1, "type": "dashed", "color": "#FFFF00"},
        },
        {
            "name": "65即將爆發",
            "type": "line",
            "data": line_65,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "showSymbol": False,
            "lineStyle": {"width": 1, "type": "dot", "color": "#C0C0C0"},
        },
        {
            "name": "80爆發線",
            "type": "line",
            "data": line_80,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "showSymbol": False,
            "lineStyle": {"width": 1, "color": "#FFFFFF"},
        },
        {
            "name": "★抄",
            "type": "scatter",
            "data": sig_chao,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "symbol": "circle",
            "symbolSize": 18,
            "itemStyle": {"color": "#FF0000"},
            "label": {
                "show": True,
                "formatter": "抄",
                "color": "#FFFFFF",
                "fontSize": 11,
                "fontWeight": "bold",
            },
        },
        {
            "name": "★加50",
            "type": "scatter",
            "data": sig_jia_50,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "symbol": "circle",
            "symbolSize": 16,
            "itemStyle": {"color": "#FFFF00"},
            "label": {
                "show": True,
                "formatter": "加",
                "color": "#000000",
                "fontSize": 11,
                "fontWeight": "bold",
            },
        },
        {
            "name": "★加65",
            "type": "scatter",
            "data": sig_jia_65,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "symbol": "circle",
            "symbolSize": 16,
            "itemStyle": {"color": "#FFFF00"},
            "label": {
                "show": True,
                "formatter": "加",
                "color": "#000000",
                "fontSize": 11,
                "fontWeight": "bold",
            },
        },
        {
            "name": "★爆",
            "type": "scatter",
            "data": sig_bao,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "symbol": "circle",
            "symbolSize": 18,
            "itemStyle": {"color": "#FFA500"},
            "label": {
                "show": True,
                "formatter": "爆",
                "color": "#000000",
                "fontSize": 12,
                "fontWeight": "bold",
            },
        },
        {
            "name": "★空",
            "type": "scatter",
            "data": sig_kong,
            "xAxisIndex": 1,
            "yAxisIndex": 1,
            "symbol": "circle",
            "symbolSize": 18,
            "itemStyle": {"color": "#00FF00"},
            "label": {
                "show": True,
                "formatter": "空",
                "color": "#000000",
                "fontSize": 11,
                "fontWeight": "bold",
            },
        },
    ]

    return series_list


def get_subchart_echarts_config(
    df: pd.DataFrame, metric_name: str = "主力資金"
):
    if metric_name == "六脈神劍":
        return {
            "yAxis": {
                "gridIndex": 1,
                "min": 0,
                "max": 105,
                "interval": 15,
                "axisLabel": {
                    "show": True,
                    "color": "#FFFFFF",
                    "fontSize": 11,
                    "fontWeight": "bold",
                    "formatter": """function (value) {
                        var labels = {
                            15: 'MACD',
                            30: 'KDJ',
                            45: 'RSI',
                            60: 'LWR',
                            75: 'BBI',
                            90: 'ZLMM'
                        };
                        return labels[value] || '';
                    }""",
                },
                "splitLine": {
                    "show": True,
                    "lineStyle": {"type": "dashed", "color": "#333333"},
                },
            }
        }

    return {
        "yAxis": {
            "gridIndex": 1,
            "min": 0,
            "max": 100,
            "splitLine": {
                "show": True,
                "lineStyle": {"type": "dashed", "color": "#333333"},
            },
        }
    }