import pandas as pd


def calculate_ma(df):
    """計算移動平均線 (MA)"""
    df["MA5"] = df["Close"].rolling(window=5).mean()
    df["MA10"] = df["Close"].rolling(window=10).mean()
    df["MA20"] = df["Close"].rolling(window=20).mean()
    df["MA60"] = df["Close"].rolling(window=60).mean()
    return df


def calculate_macd(df, fast=12, slow=26, signal=9):
    """計算 MACD 指標"""
    exp1 = df["Close"].ewm(span=fast, adjust=False).mean()
    exp2 = df["Close"].ewm(span=slow, adjust=False).mean()
    df["DIF"] = exp1 - exp2
    df["MACD"] = df["DIF"].ewm(span=signal, adjust=False).mean()
    df["MACD_Hist"] = df["DIF"] - df["MACD"]
    return df


def calculate_kd(df, n=9):
    """計算 KD 指標"""
    low_list = df["Low"].rolling(window=n).min()
    high_list = df["High"].rolling(window=n).max()

    rsv = (df["Close"] - low_list) / (high_list - low_list) * 100
    rsv = rsv.fillna(50)

    k = [50.0]
    d = [50.0]

    for i in range(1, len(rsv)):
        current_k = (2 / 3) * k[-1] + (1 / 3) * rsv.iloc[i]
        current_d = (2 / 3) * d[-1] + (1 / 3) * current_k
        k.append(current_k)
        d.append(current_d)

    df["K"] = k
    df["D"] = d
    return df


def calculate_rsi(df, period=14):
    """計算 RSI 指標"""
    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))
    df["RSI"] = df["RSI"].fillna(50)
    return df


def add_all_indicators(df):
    """主進入點：一鍵計算所有技術指標"""
    if df is None or df.empty:
        return df

    df = calculate_ma(df)
    df = calculate_macd(df)
    df = calculate_kd(df)
    df = calculate_rsi(df)

    return df