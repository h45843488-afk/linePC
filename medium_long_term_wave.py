# -*- coding: utf-8 -*-
"""
中長期波段指標
=========================================================
第三版：中長期方向線

測試規則：
    圖標 23 = 買進
    圖標 24 = 出場

本版本以回測版本為基準。

暫時不加入：
    ABC1
    成交量
    突破
    MA 過濾
    其他額外條件
=========================================================
"""

import numpy as np
import pandas as pd


# =========================================================
# 主計算
# =========================================================
def calculate_medium_long_term_wave(df):

    df = df.copy()

    # =====================================================
    # 通達信 CROSS
    #
    # CROSS(A,B)
    # = 今天 A > B
    #   且昨天 A <= B
    # =====================================================

    def tdx_cross(a, b):

        return (
            (a > b)
            &
            (a.shift(1) <= b.shift(1))
        ).fillna(False)

    # =====================================================
    # 基本資料
    # =====================================================

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)

    # =====================================================
    # 日期條件
    #
    # 原公式：
    #
    # SJTJ:=DATE<1590301;
    # =====================================================

    if isinstance(df.index, pd.DatetimeIndex):

        date_number = (
            df.index.year % 100 * 10000
            +
            df.index.month * 100
            +
            df.index.day
        )

        sjtj = (
            date_number < 1590301
        )

    else:

        sjtj = pd.Series(
            True,
            index=df.index
        )

    sjtj = pd.Series(
        sjtj,
        index=df.index
    ).fillna(False)

    # =====================================================
    # =====================================================
    # 第一部分：長期方向
    # =====================================================
    # =====================================================

    # =====================================================
    # ① AA
    #
    # AA:=ABS(
    #     (2*CLOSE+HIGH+LOW)/4
    #     -MA(CLOSE,30)
    #     )
    #     /MA(CLOSE,30);
    # =====================================================

    typical_price = (
        2 * close
        + high
        + low
    ) / 4

    ma30 = (
        close
        .rolling(
            window=30,
            min_periods=1
        )
        .mean()
    )

    aa = (
        (
            typical_price
            - ma30
        ).abs()
        /
        ma30.replace(
            0,
            np.nan
        )
    )

    aa = (
        aa
        .replace(
            [np.inf, -np.inf],
            np.nan
        )
        .fillna(0)
    )

    # =====================================================
    # ② 長期波動
    #
    # 長期波動:=DMA(
    #     (2*CLOSE+LOW+HIGH)/4,
    #     AA
    # );
    #
    # DMA：
    # Y = A*X + (1-A)*Y前值
    # =====================================================

    long_volatility = pd.Series(
        np.nan,
        index=df.index,
        dtype=float
    )

    for i in range(len(df)):

        current_price = (
            2 * close.iloc[i]
            + low.iloc[i]
            + high.iloc[i]
        ) / 4

        current_aa = aa.iloc[i]

        if i == 0:

            long_volatility.iloc[i] = (
                current_price
            )

        else:

            previous_value = (
                long_volatility.iloc[i - 1]
            )

            long_volatility.iloc[i] = (
                current_aa
                * current_price
                +
                (
                    1 - current_aa
                )
                * previous_value
            )

    # =====================================================
    # ③ CC
    #
    # CC:=(CLOSE/長期波動);
    # =====================================================

    cc = (
        close
        /
        long_volatility.replace(
            0,
            np.nan
        )
    )

    # =====================================================
    # ④ MA1
    #
    # MA1:=MA(
    #     CC*(2*CLOSE+HIGH+LOW)/4,
    #     3
    # );
    # =====================================================

    ma1_source = (
        cc
        * typical_price
    )

    ma1 = (
        ma1_source
        .rolling(
            window=3,
            min_periods=1
        )
        .mean()
    )

    # =====================================================
    # ⑤ MAAA
    #
    # MAAA:=
    # ((MA1-長期波動)/長期波動)/3;
    # =====================================================

    maaa = (
        (
            ma1
            - long_volatility
        )
        /
        long_volatility.replace(
            0,
            np.nan
        )
    ) / 3

    # =====================================================
    # ⑥ VARG
    #
    # VARG:=MA1-MAAA*MA1;
    # =====================================================

    varg = (
        ma1
        -
        maaa * ma1
    )

    # =====================================================
    # ⑦ 長期方向
    #
    # VARG > 長期波動 = 紅
    # VARG <= 長期波動 = 綠
    # =====================================================

    long_up = (
        sjtj
        &
        (varg > long_volatility)
    ).fillna(False)

    long_down = (
        sjtj
        &
        (varg <= long_volatility)
    ).fillna(False)

    # =====================================================
    # ⑧ 圖標 23
    #
    # HZS:=CROSS(VARG,長期波動);
    #
    # 圖標 23 = 綠轉紅
    #
    # 這部分完全保持原回測版本。
    # =====================================================

    hzs = (
        tdx_cross(
            varg,
            long_volatility
        )
        &
        sjtj
    ).fillna(False)

    # =====================================================
    # 圖標 24
    #
    # 原本使用：
    #
    # LZS:=CROSS(長期波動,VARG);
    #
    # 但實際綠線條件為：
    #
    # VARG <= 長期波動
    #
    # 為使圖標24與「綠線第一次出現」完全同步，
    # 改為：
    #
    # 今天綠線成立
    # 且昨天不是綠線
    #
    # = 綠線開始當天
    # =====================================================

    lzs = (
        long_down
        &
        ~long_down.shift(1).fillna(False)
    ).fillna(False)

    # =====================================================
    # =====================================================
    # 第二部分：中期方向
    # =====================================================
    # =====================================================

    # =====================================================
    # ⑨ MAH
    #
    # MAH :=
    # (H*18 + REF(H,1)*17 + ... + REF(H,17)*1) / 171
    # =====================================================

    mah = pd.Series(
        0.0,
        index=df.index
    )

    mal = pd.Series(
        0.0,
        index=df.index
    )

    for n in range(18):

        weight = 18 - n

        mah = (
            mah
            +
            high.shift(n).fillna(high)
            * weight
        )

        mal = (
            mal
            +
            low.shift(n).fillna(low)
            * weight
        )

    mah = mah / 171
    mal = mal / 171

    # =====================================================
    # ⑩ MA5 / MA10 / MA20 / MA60
    # =====================================================

    ma5 = (
        close
        .rolling(
            window=5,
            min_periods=1
        )
        .mean()
    )

    ma10 = (
        close
        .rolling(
            window=10,
            min_periods=1
        )
        .mean()
    )

    ma20 = (
        close
        .rolling(
            window=20,
            min_periods=1
        )
        .mean()
    )

    ma60 = (
        close
        .rolling(
            window=60,
            min_periods=1
        )
        .mean()
    )

    # =====================================================
    # ⑪ VAR1
    #
    # VAR1 :=
    # SJTJ AND
    # (
    #     CLOSE>=MAH
    #     OR
    #     (
    #       C>MA5 AND
    #       C>MA10 AND
    #       C>MA20 AND
    #       C>MA60
    #     )
    # );
    # =====================================================

    var1 = (
        sjtj
        &
        (
            (close >= mah)
            |
            (
                (close > ma5)
                &
                (close > ma10)
                &
                (close > ma20)
                &
                (close > ma60)
            )
        )
    ).fillna(False)

    # =====================================================
    # ⑫ KK
    #
    # KK :=
    # SJTJ AND
    # (
    #     MAL>CLOSE
    #     OR
    #     (
    #       C<MA5 AND
    #       C<MA10 AND
    #       C<MA20 AND
    #       C<MA60
    #     )
    # );
    # =====================================================

    kk = (
        sjtj
        &
        (
            (mal > close)
            |
            (
                (close < ma5)
                &
                (close < ma10)
                &
                (close < ma20)
                &
                (close < ma60)
            )
        )
    ).fillna(False)

    # =====================================================
    # ⑬ BARSLAST
    #
    # 通達信：
    #
    # BARSLAST(X)
    # = 距離最近一次 X 成立經過多少根 K
    # =====================================================

    def tdx_barslast(condition):

        result = np.full(
            len(condition),
            np.nan,
            dtype=float
        )

        count = np.nan

        for i, value in enumerate(
            condition.fillna(False)
        ):

            if bool(value):

                count = 0

            elif not np.isnan(count):

                count += 1

            result[i] = count

        return pd.Series(
            result,
            index=condition.index
        )

    var11 = tdx_barslast(var1)
    kk1 = tdx_barslast(kk)

    # =====================================================
    # ⑭
    #
    # VAR12:=BARSLAST(CROSS(KK1,VAR11));
    # KK2:=BARSLAST(CROSS(VAR11,KK1));
    # =====================================================

    cross_kk1_var11 = tdx_cross(
        kk1,
        var11
    )

    cross_var11_kk1 = tdx_cross(
        var11,
        kk1
    )

    var12 = tdx_barslast(
        cross_kk1_var11
    )

    kk2 = tdx_barslast(
        cross_var11_kk1
    )

    # =====================================================
    # ⑮ HS / LS
    #
    # HS:=VAR12<KK2;
    # LS:=KK2<VAR12;
    # =====================================================

    hs = (
        var12
        <
        kk2
    ).fillna(False)

    ls = (
        kk2
        <
        var12
    ).fillna(False)

    hs = (
        hs
        &
        sjtj
    )

    ls = (
        ls
        &
        sjtj
    )

    # =====================================================
    # ⑯ 中期波動
    #
    # 波動:=(MAH+MAL)/2;
    # =====================================================

    medium_volatility = (
        mah
        +
        mal
    ) / 2

    medium_up = hs.copy()
    medium_down = ls.copy()

    # =====================================================
    # 第三部分：中長期整合
    #
    # 圖標23 → 買
    # 圖標24 → 賣
    # =====================================================

    buy_signal = hzs.copy()
    sell_signal = lzs.copy()

    # =====================================================
    # 回測引擎需要的欄位
    # =====================================================

    df["長期波動"] = (
        long_volatility
    )

    df["VARG"] = (
        varg
    )

    df["長期方向上升"] = (
        long_up
    )

    df["長期方向下降"] = (
        long_down
    )

    # =====================================================
    # 中期方向欄位
    # =====================================================

    df["MAH"] = (
        mah
    )

    df["MAL"] = (
        mal
    )

    df["中期波動"] = (
        medium_volatility
    )

    df["中級方向上升"] = (
        medium_up
    )

    df["中級方向下降"] = (
        medium_down
    )

    df["HS"] = (
        hs
    )

    df["LS"] = (
        ls
    )

    # =====================================================
    # 圖標 23 / 24
    # =====================================================

    df["HZS"] = (
        hzs
    )

    df["LZS"] = (
        lzs
    )

    # =====================================================
    # 買入訊號
    #
    # 圖標23
    # =====================================================

    df["Buy_Signal"] = (
        buy_signal
    )

    # =====================================================
    # 賣出訊號
    #
    # 圖標24
    # =====================================================

    df["Sell_Signal"] = (
        sell_signal
    )

    # =====================================================
    # 買入原因
    # =====================================================

    df["Buy_Reason"] = np.where(
        buy_signal,
        "圖標23：中長期方向綠轉紅",
        ""
    )

    # =====================================================
    # 賣出原因
    # =====================================================

    df["Sell_Reason"] = np.where(
        sell_signal,
        "圖標24：中長期方向紅轉綠",
        ""
    )

    return df


# =========================================================
# app.py / 副圖呼叫入口
# =========================================================

def get_medium_long_term_wave_data(df):
    return calculate_medium_long_term_wave(df)