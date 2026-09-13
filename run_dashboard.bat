@echo off
chcp 65001 > nul
title 啟動台股智慧哨兵戰情室

F:
cd /d "%~dp0"

echo 正在啟動 Web 介面並自動開啟瀏覽器...
echo ========================================
echo 提示：目前已切換至模組化架構 (app.py + indicators.py + data_fetcher.py)
echo ========================================

py -m streamlit run app.py

pause