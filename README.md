# FinGroww Trading Arena 🚀

Advanced Real-Time Indian Stock Trading Intelligence Platform with Master Confluence Oscillator Engine, Verified Backtest Audit, and Real-Time NSE / Yahoo Market Proxy.

## 🌟 Features
- **Master Confluence Oscillator (-100 to +100)**: Combines Supertrend, Session VWAP, EMA 21/50, Wilder RSI (14), ADX (14), and Volume Expansion.
- **Interactive Candlestick Chart**: Fullview, Drag Panning, Mouse Wheel Zooming, and Timeframe switching (1m, 5m, 15m, 1H, 1D).
- **Verified Backtest Engine**: Forward simulation with zero lookahead bias and win rate audit badges.
- **Dynamic Crosshair & Floating HUD**: Real-time OHLC, Volume, Master Score, Entry, SL, and Target 1/2/3 levels.
- **Python Flask Backend Proxy**: Real-time ticker price fetcher for NSE stocks and indices.

## 🚀 Cloud Deployment Guide

### Backend Server (Render.com)
- Build Command: `pip install -r requirements_fingroww.txt`
- Start Command: `gunicorn fingroww_market_server:app`

### Frontend UI (Vercel / Netlify)
- Serve `fingroww_trading_intelligence_NSE.html` (or `index.html`).
