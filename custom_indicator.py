import numpy as np
import pandas as pd


def tdx_resonance_strategy(df: pd.DataFrame) -> pd.DataFrame:
    """通達信多指標共振策略轉 Python 實現

    輸入: df 需包含 open/high/low/close/volume 列（大小寫皆可）
    輸出: 新增所有中間指標和訊號的 DataFrame
    """
    df = df.copy()

    # 自動相容大小寫欄位名稱
    CLOSE = df['close'] if 'close' in df.columns else df['Close']
    HIGH = df['high'] if 'high' in df.columns else df['High']
    LOW = df['low'] if 'low' in df.columns else df['Low']

    # ========== 1. MACD (DIFF/DEA) ==========
    ema_fast = CLOSE.ewm(span=8, adjust=False).mean()
    ema_slow = CLOSE.ewm(span=13, adjust=False).mean()
    DIFF = ema_fast - ema_slow
    DEA = DIFF.ewm(span=5, adjust=False).mean()
    df['DIFF'] = DIFF
    df['DEA'] = DEA
    df['ABC1'] = DIFF > DEA

    # ========== 2. KDJ (K/D) ==========
    llv_low_8 = LOW.rolling(window=8, min_periods=1).min()
    hhv_high_8 = HIGH.rolling(window=8, min_periods=1).max()
    rsv = (
        (CLOSE - llv_low_8) / (hhv_high_8 - llv_low_8).replace(0, np.nan) * 100
    )

    def sma(series, n, m):
        """通達信 SMA 函數：遞迴加權移動平均"""
        result = np.zeros_like(series, dtype=float)
        prev = series.iloc[0]
        result[0] = prev
        for i in range(1, len(series)):
            prev = (m * series.iloc[i] + (n - m) * prev) / n
            result[i] = prev
        return pd.Series(result, index=series.index)

    K = sma(rsv.fillna(0), 3, 1)
    D = sma(K, 3, 1)
    df['K'] = K
    df['D'] = D
    df['ABC2'] = K > D

    # ========== 3. RSI (RSI1/RSI2) ==========
    REF_CLOSE = CLOSE.shift(1)  # REF(CLOSE,1)
    delta = CLOSE - REF_CLOSE

    MAX_CLOSE = delta.clip(lower=0)  # MAX(CLOSE-REF,0)
    ABS_CLOSE = delta.abs()  # ABS(CLOSE-REF)

    sma_max_5 = sma(MAX_CLOSE.fillna(0), 5, 1)
    sma_abs_5 = sma(ABS_CLOSE.fillna(0), 5, 1)
    RSI1 = sma_max_5 / sma_abs_5.replace(0, np.nan) * 100

    sma_max_13 = sma(MAX_CLOSE.fillna(0), 13, 1)
    sma_abs_13 = sma(ABS_CLOSE.fillna(0), 13, 1)
    RSI2 = sma_max_13 / sma_abs_13.replace(0, np.nan) * 100

    df['RSI1'] = RSI1
    df['RSI2'] = RSI2
    df['ABC3'] = RSI1 > RSI2

    # ========== 4. LWR (LWR1/LWR2) ==========
    hhv_high_13 = HIGH.rolling(window=13, min_periods=1).max()
    llv_low_13 = LOW.rolling(window=13, min_periods=1).min()
    lwr_raw = (
        -(hhv_high_13 - CLOSE)
        / (hhv_high_13 - llv_low_13).replace(0, np.nan)
        * 100
    )

    LWR1 = sma(lwr_raw.fillna(0), 3, 1)
    LWR2 = sma(LWR1, 3, 1)
    df['LWR1'] = LWR1
    df['LWR2'] = LWR2
    df['ABC4'] = LWR1 > LWR2

    # ========== 5. BBI ==========
    BBI = (
        CLOSE.rolling(3).mean()
        + CLOSE.rolling(5).mean()
        + CLOSE.rolling(8).mean()
        + CLOSE.rolling(13).mean()
    ) / 4
    df['BBI'] = BBI
    df['ABC5'] = CLOSE > BBI

    # ========== 6. MTM (ZLMM) ==========
    MTM = CLOSE - REF_CLOSE
    ema_mtm_5 = MTM.ewm(span=5, adjust=False).mean()
    ema_ema_mtm_5 = ema_mtm_5.ewm(span=3, adjust=False).mean()
    ema_abs_mtm_5 = MTM.abs().ewm(span=5, adjust=False).mean()
    ema_abs2_mtm_5 = ema_abs_mtm_5.ewm(span=3, adjust=False).mean()
    MMS = 100 * ema_ema_mtm_5 / ema_abs2_mtm_5.replace(0, np.nan)

    ema_mtm_13 = MTM.ewm(span=13, adjust=False).mean()
    ema_ema_mtm_13 = ema_mtm_13.ewm(span=8, adjust=False).mean()
    ema_abs_mtm_13 = MTM.abs().ewm(span=13, adjust=False).mean()
    ema_abs2_mtm_13 = ema_abs_mtm_13.ewm(span=8, adjust=False).mean()
    MMM = 100 * ema_ema_mtm_13 / ema_abs2_mtm_13.replace(0, np.nan)

    df['MMS'] = MMS
    df['MMM'] = MMM
    df['ABC6'] = MMS > MMM

    # ========== 7. 共振訊號 ==========
    df['共振'] = (
        df['ABC1']
        & df['ABC2']
        & df['ABC3']
        & df['ABC4']
        & df['ABC5']
        & df['ABC6']
    )

    # 買入：共振從前序非共振到當前共振（上穿）
    prev_resonance = df['共振'].shift(1).fillna(False)
    df['買入'] = df['共振'] & ~prev_resonance

    # 持有：當前處於共振狀態
    df['持有'] = df['共振']

    return df