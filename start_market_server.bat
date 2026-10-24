@echo off
title FinGroww Live Market Server (Port 8787)
color 0A
echo ========================================================
echo        FinGroww Quantitative Trading Intelligence
echo        Starting Local High-Speed Market Proxy...
echo ========================================================
echo.
cd /d "%~dp0"
python fingroww_market_server.py
if errorlevel 1 (
    echo.
    echo [ERROR] Python not found or failed to start.
    echo Trying py launcher...
    py fingroww_market_server.py
)
pause
