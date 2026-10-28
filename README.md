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

### Paper Trading Data Persistence
- Paper trading profiles, account state, open positions, and full closed-trade history are saved to MongoDB when `MONGODB_URI` (or `mongo_url`) is configured.
- The backend also saves a durable local SQLite copy at `data/paper_trading.db` by default. Set `FINGROWW_PAPER_DB_PATH` to choose another location.
- On deployments with an ephemeral filesystem, configure MongoDB or mount persistent storage and point `FINGROWW_PAPER_DB_PATH` to it; otherwise local SQLite data will not survive a platform instance replacement.
- Profiles are isolated by their profile name. Profile names are not authenticated accounts; do not treat them as access control for private user data.

### Auto Paper-Trade Entry Rules
- New auto entries require NSE's confirmed regular-session status (weekdays, 09:15–15:30 IST), a fresh NSE cash-equity quote, and recent completed 15-minute candles. An unavailable exchange-status/quote feed blocks entries; there is no fallback to sample prices or simulated price drift.
- Starting or resuming the auto engine is rejected while NSE is closed or its status is unavailable. A cached "open" status is rechecked against current IST session time before it can authorize trading.
- The scanner uses one explicit setup: EMA20 above/below EMA50 with trend slope, completed-candle confirmation, session VWAP alignment, a live-price breakout beyond the last completed candle, and at least 1.2x the preceding 20-candle average volume.
- Entry is the fresh NSE LTP plus the simulator's modeled execution slippage. Stop distance is 1.5x ATR(14), with a 0.2% minimum; targets use the profile's minimum risk/reward (1.5R–2R).
- Auto entries currently support cash equities only. Index/stock futures and options are not opened because this application does not yet obtain verified live prices for the actual futures/options contracts. Yahoo Finance is used only for indicator candles, never as an execution quote.
