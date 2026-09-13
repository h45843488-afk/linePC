import streamlit as st
import pandas as pd

def render_risk_card(df: pd.DataFrame):
    """【🛡️ 實戰風控與關鍵關卡】完全無粗體、極簡清爽版"""
    
    # 柔和色系 (取消所有粗體，僅保留色彩點綴)
    c_gray = "#888888"
    c_red = "#FF6B6B"     # 柔紅
    c_green = "#51CF66"   # 柔綠
    c_yellow = "#FCC419"  # 柔黃

    buy_html = f'<span style="color: {c_gray}; font-weight: normal;">--</span>'
    sell_html = f'<span style="color: {c_gray}; font-weight: normal;">--</span>'
    stop_html = f'<span style="color: {c_gray}; font-weight: normal;">--</span>'

    long_status_html = f'<span style="color: {c_gray}; font-weight: normal;">觀望</span>'
    long_defense_html = f'<span style="color: {c_gray}; font-weight: normal;">--</span>'

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        st.warning("目前無有效股票資料")
        return

    latest_idx = df.index[-1]
    latest_close = df.loc[latest_idx, "Close"]

    # 1. 短線條件檢查
    has_yellow = False
    if ("E" in df.columns) and ("D" in df.columns):
        val_e = df.loc[latest_idx, "E"]
        val_d = df.loc[latest_idx, "D"]
        if pd.notna(val_e) and pd.notna(val_d):
            has_yellow = bool(val_e > val_d)

    has_red = False
    if "ZYG_Red" in df.columns and pd.notna(df.loc[latest_idx, "ZYG_Red"]):
        has_red = True
    elif ("ZYG29" in df.columns) and ("ZYG30" in df.columns):
        val_29 = df.loc[latest_idx, "ZYG29"]
        val_30 = df.loc[latest_idx, "ZYG30"]
        if pd.notna(val_29) and pd.notna(val_30):
            has_red = bool(val_29 > val_30)

    # 短線狀態判斷（全一般字體）
    if has_yellow and has_red:
        buy_html = f'<span style="color: {c_red}; font-weight: normal;">{latest_close:.1f}</span>'
        sell_html = f'<span style="color: {c_green}; font-weight: normal;">續抱</span>'
        if "MA10" in df.columns and pd.notna(df.loc[latest_idx, "MA10"]):
            ma10_val = df.loc[latest_idx, "MA10"]
            stop_html = f'<span style="color: {c_yellow}; font-weight: normal;">{ma10_val:.1f}</span>'
            
    elif not has_red and not has_yellow:
        sell_html = f'<span style="color: {c_green}; font-weight: normal;">{latest_close:.1f}</span>'
        
    else:
        sell_html = f'<span style="color: {c_yellow}; font-weight: normal;">警戒</span>'

    # 2. 中長線條件檢查（全一般字體）
    if "MA60" in df.columns and pd.notna(df.loc[latest_idx, "MA60"]):
        ma60_val = df.loc[latest_idx, "MA60"]
        if latest_close >= ma60_val:
            long_status_html = f'<span style="color: {c_red}; font-weight: normal;">多頭波段</span>'
            long_defense_html = f'<span style="color: {c_yellow}; font-weight: normal;">{ma60_val:.1f}</span>'
        else:
            long_status_html = f'<span style="color: {c_gray}; font-weight: normal;">空頭/觀望</span>'

    # 3. 渲染 HTML 戰情卡片（強制容器內全體使用 font-weight: normal）
    html_str = f'''
    <div class="stock-info-card" style="font-weight: normal;">
        <div class="metric-title" style="margin-bottom: 8px; font-weight: normal; color: #FFFFFF;">🛡️ 實戰風控與關鍵關卡</div>
        <div class="metric-row" style="margin-bottom: 6px; font-size: 0.8em; font-weight: normal;">
            <span class="metric-label" style="color: #A0A0A0; font-weight: normal;">短線：</span>
            <span class="metric-value" style="color: #DDDDDD; font-weight: normal;">
                買 {buy_html} &nbsp;|&nbsp; 
                賣 {sell_html} &nbsp;|&nbsp; 
                停損 {stop_html}
            </span>
        </div>
        <div class="metric-row" style="font-size: 0.8em; font-weight: normal;">
            <span class="metric-label" style="color: #A0A0A0; font-weight: normal;">中長：</span>
            <span class="metric-value" style="color: #DDDDDD; font-weight: normal;">
                趨勢 {long_status_html} &nbsp;|&nbsp; 
                季線防守 {long_defense_html}
            </span>
        </div>
    </div>
    '''
    st.sidebar.markdown(html_str, unsafe_allow_html=True)