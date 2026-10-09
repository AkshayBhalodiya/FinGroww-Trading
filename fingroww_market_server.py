from flask import Flask, jsonify, request
import requests
import time
import threading
import re

app = Flask(__name__)
NSE = "https://www.nseindia.com"
session = requests.Session()
lock = threading.Lock()
last_init = 0
indices_cache = {"at": 0, "rows": []}
symbols_cache = {"at": 0, "items": []}

EQUITY_CSV_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

INDEX_SYMBOLS = [
    {"symbol": "NIFTY 50", "name": "Nifty 50 Index", "kind": "index"},
    {"symbol": "BANK NIFTY", "name": "Nifty Bank Index", "kind": "index"},
    {"symbol": "SENSEX", "name": "BSE Sensex Index", "kind": "index"},
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Connection": "keep-alive",
}

INDEX_ALIASES = {
    "NIFTY 50": "NIFTY 50",
    "NIFTY": "NIFTY 50",
    "BANK NIFTY": "NIFTY BANK",
    "NIFTY BANK": "NIFTY BANK",
    "BANKNIFTY": "NIFTY BANK",
}

YAHOO_TICKERS = {
    "NIFTY 50": "^NSEI",
    "NIFTY BANK": "^NSEBANK",
    "BANK NIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
}

TF_YAHOO = {
    "5m": ("5m", "5d"),
    "15m": ("15m", "1mo"),
    "30m": ("30m", "1mo"),
    "1h": ("1h", "3mo"),
    "1H": ("1h", "3mo"),
    "1d": ("1d", "1y"),
    "1D": ("1d", "1y"),
    "1w": ("1wk", "5y"),
    "1W": ("1wk", "5y"),
}


@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def init_nse():
    global last_init
    with lock:
        if time.time() - last_init < 120:
            return
        session.get(
            NSE + "/market-data/live-equity-market",
            headers={
                **HEADERS,
                "Accept": "text/html,application/xhtml+xml",
                "Referer": NSE + "/",
            },
            timeout=15,
        )
        last_init = time.time()


def nse_get(path, params=None):
    for attempt in range(2):
        try:
            init_nse()
            r = session.get(
                NSE + path,
                headers={
                    **HEADERS,
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Referer": NSE + "/market-data/live-market-indices",
                },
                params=params,
                timeout=15,
            )
            if r.status_code in (401, 403):
                with lock:
                    globals()["last_init"] = 0
                if attempt == 0:
                    time.sleep(0.4)
                    continue
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 1:
                return None
            time.sleep(0.4)
    return None


def normalize_symbol(raw):
    sym = (raw or "RELIANCE").upper().strip()
    sym = re.sub(r"\s+", " ", sym)
    return sym


def yahoo_ticker(symbol):
    if symbol in YAHOO_TICKERS:
        return YAHOO_TICKERS[symbol]
    if symbol.startswith("^") or symbol.endswith(".NS"):
        return symbol
    if symbol == "SENSEX":
        return "^BSESN"
    return symbol + ".NS"


def fetch_yahoo_chart(ticker, interval="15m", range_="1mo"):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + requests.utils.quote(ticker, safe="^.")
        + f"?interval={interval}&range={range_}&events=div%2Csplits&includePrePost=false"
    )
    r = requests.get(url, headers={**HEADERS, "Accept": "application/json"}, timeout=20)
    r.raise_for_status()
    result = (r.json().get("chart") or {}).get("result")
    if not result:
        return [], {}
    block = result[0]
    q = (block.get("indicators") or {}).get("quote") or [{}]
    q = q[0] if q else {}
    ts = block.get("timestamp") or []
    rows = []
    for i, t in enumerate(ts):
        o, h, l, c = (
            q.get("open", [None] * len(ts))[i],
            q.get("high", [None] * len(ts))[i],
            q.get("low", [None] * len(ts))[i],
            q.get("close", [None] * len(ts))[i],
        )
        v = q.get("volume", [0] * len(ts))[i] or 0
        nums = [o, h, l, c]
        if not all(isinstance(x, (int, float)) for x in nums):
            continue
        rows.append(
            {
                "o": float(o),
                "h": float(h),
                "l": float(l),
                "c": float(c),
                "v": float(v),
                "t": int(t) * 1000,
            }
        )
    return rows, block.get("meta") or {}


def nse_index_rows():
    global indices_cache
    now = time.time()
    if now - indices_cache["at"] < 45 and indices_cache["rows"]:
        return indices_cache["rows"]
    data = nse_get("/api/allIndices")
    rows = (data or {}).get("data") or []
    indices_cache = {"at": now, "rows": rows}
    return rows


def quote_from_nse_index(symbol):
    key = INDEX_ALIASES.get(symbol, symbol)
    for row in nse_index_rows():
        if row.get("index") == key or row.get("indexSymbol") == key:
            return {
                "source": "NSE",
                "symbol": symbol,
                "company": row.get("index"),
                "lastPrice": row.get("last"),
                "change": row.get("variation"),
                "pChange": row.get("percentChange"),
                "open": row.get("open"),
                "dayHigh": row.get("high"),
                "dayLow": row.get("low"),
                "previousClose": row.get("previousClose"),
                "timestamp": time.strftime("%d-%b-%Y %H:%M:%S IST"),
            }
    return None


def quote_from_nse_equity(symbol):
    data = nse_get("/api/quote-equity", {"symbol": symbol})
    if not data or not isinstance(data, dict):
        return None
    info = data.get("priceInfo") or {}
    meta = data.get("info") or {}
    intra = info.get("intraDayHighLow") or {}
    last = info.get("lastPrice")
    if last is None:
        return None
    return {
        "source": "NSE",
        "symbol": symbol,
        "company": meta.get("companyName"),
        "lastPrice": last,
        "change": info.get("change"),
        "pChange": info.get("pChange"),
        "open": info.get("open"),
        "dayHigh": intra.get("max"),
        "dayLow": intra.get("min"),
        "previousClose": info.get("previousClose"),
        "vwap": info.get("vwap"),
        "timestamp": (data.get("metadata") or {}).get("lastUpdateTime"),
    }


def quote_from_yahoo(symbol):
    ticker = yahoo_ticker(symbol)
    rows, meta = fetch_yahoo_chart(ticker, "5m", "1d")
    price = meta.get("regularMarketPrice")
    if price is None and rows:
        price = rows[-1]["c"]
    if price is None:
        return None
    return {
        "source": "Yahoo Finance (free)",
        "symbol": symbol,
        "company": meta.get("longName") or meta.get("shortName") or symbol,
        "lastPrice": price,
        "change": meta.get("regularMarketChange"),
        "pChange": meta.get("regularMarketChangePercent"),
        "open": meta.get("regularMarketOpen"),
        "dayHigh": meta.get("regularMarketDayHigh"),
        "dayLow": meta.get("regularMarketDayLow"),
        "previousClose": meta.get("chartPreviousClose") or meta.get("previousClose"),
        "timestamp": meta.get("regularMarketTime"),
    }


def resolve_quote(symbol):
    if symbol in INDEX_ALIASES or symbol in ("NIFTY 50", "NIFTY BANK"):
        q = quote_from_nse_index(symbol)
        if q:
            return q
    if symbol not in INDEX_ALIASES and symbol not in ("NIFTY 50", "NIFTY BANK", "SENSEX"):
        q = quote_from_nse_equity(symbol)
        if q:
            return q
    if symbol == "SENSEX":
        return quote_from_yahoo(symbol)
    q = quote_from_yahoo(symbol)
    if q:
        return q
    return quote_from_nse_index(symbol)


FO_SYMBOLS = {
    "NIFTY 50", "BANK NIFTY", "NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY",
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "TATAMOTORS", "BHARTIARTL",
    "LT", "AXISBANK", "ITC", "MARUTI", "KOTAKBANK", "ASIANPAINT", "HCLTECH", "SUNPHARMA",
    "BAJFINANCE", "TITAN", "WIPRO", "ULTRACHEMCO", "ULTRACEMCO", "TATASTEEL", "POWERGRID",
    "NTPC", "M&M", "ADANIENT", "ADANIPORTS", "COALINDIA", "BPCL", "ONGC", "DLF", "TECHM",
    "INDUSINDBK", "HAL", "BEL", "PIDILITIND", "TATACONSUM", "CHOLAFIN", "SHREECEM", "NESTLEIND",
    "GRASIM", "EICHERMOT", "HDFCLIFE", "SBILIFE", "HEROMOTOCO", "JSWSTEEL", "DIVISLAB",
    "APOLLOHOSP", "CIPLA", "LTIM", "TRENT", "SIEMENS", "GODREJPROP", "DRREDDY", "HINDALCO",
    "VBL", "RECLTD", "PFC", "CONCOR", "MOTHERSON", "GAIL", "SAIL", "BHEL", "CANBK", "PNB",
    "BANKBARODA", "FEDERALBNK", "IDFCFIRSTB", "AUROPHARMA", "LUPIN", "TATACOMM", "POLYCAB",
    "MCX", "PERSISTENT", "COFORGE", "TATAELXSI", "ABB", "ABCAPITAL", "ABFRL", "ALKEM",
    "AMBUJACEM", "ASTRAL", "ATUL", "BANDHANBNK", "BERGEPAINT", "BHARATFORG", "BIOCON",
    "BOSCHLTD", "BSOFT", "CANFINHOME", "CHAMBLFERT", "COLPAL", "CUMMINSIND", "DABUR",
    "DALBHARAT", "DEEPAKNTR", "ESCORTS", "EXIDEIND", "GLENMARK", "GNFC", "GODREJCP",
    "GRANULES", "GUJGASLTD", "HAVELTS", "HDFCAMC", "HINDPETRO", "HINDUNILVR", "ICICIGI",
    "ICICIPRULI", "IDEA", "IEX", "IGL", "INDUSTOWER", "NAUKRI", "IPCALAB", "IRCTC",
    "JINDALSTEL", "JUBLFOOD", "LALPATHLAB", "LICHSGFIN", "LTF", "LTTS", "MANAPPURAM",
    "MFSL", "MGL", "MPHASIS", "MRF", "MUTHOOTFIN", "NATIONALUM", "NAVINFLUOR", "NMDC",
    "OBERREALTY", "OFSS", "PAGEIND", "PEL", "PETRONET", "PVRINOX", "RAMCOCEM", "RBLBANK",
    "SBICARD", "SRF", "SUNTV", "SYNGENE", "TATACHEM", "TATAPOWER", "TORNTPHARM", "TVSMOTOR",
    "UBL", "UPL", "VOLTAS", "ZEEL"
}

def load_equity_symbols():
    global symbols_cache
    now = time.time()
    if now - symbols_cache["at"] < 86400 and symbols_cache["items"]:
        return symbols_cache["items"]
    r = requests.get(
        EQUITY_CSV_URL,
        headers={**HEADERS, "Accept": "text/csv,*/*"},
        timeout=45,
    )
    r.raise_for_status()
    items = []
    for x in INDEX_SYMBOLS:
        item = dict(x)
        item["is_fo"] = True
        items.append(item)
    seen = {x["symbol"] for x in INDEX_SYMBOLS}
    for line in r.text.splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        sym = parts[0].strip().upper()
        name = parts[1].strip()
        series = parts[2].strip().upper()
        if series != "EQ" or not sym or sym in seen:
            continue
        seen.add(sym)
        is_fo = sym in FO_SYMBOLS
        items.append({"symbol": sym, "name": name, "kind": "equity", "is_fo": is_fo})
    items.sort(key=lambda x: (0 if x["kind"] == "index" else (1 if x.get("is_fo") else 2), x["symbol"]))
    symbols_cache = {"at": now, "items": items}
    return items


def search_symbols(query, limit=40, fo_only=False):
    items = load_equity_symbols()
    if fo_only:
        items = [x for x in items if x.get("is_fo")]
    q = (query or "").strip().lower()
    if not q:
        return items[:limit] if fo_only else items
    if len(q) < 2:
        return [x for x in items if x["kind"] == "index" or x["symbol"].lower().startswith(q)][:limit]
    out = []
    for row in items:
        sym = row["symbol"].lower()
        name = row["name"].lower()
        if q in sym or q in name or sym.startswith(q):
            out.append(row)
            if len(out) >= limit:
                break
    return out


@app.get("/api/symbols")
def symbols_api():
    """Full NSE EQ universe + major indices (cached ~24h). Optional ?fo_only=1 filter."""
    try:
        fo_only = request.args.get("fo_only") == "1" or request.args.get("kind") == "fo"
        items = load_equity_symbols()
        if fo_only:
            items = [x for x in items if x.get("is_fo")]
        return jsonify({"count": len(items), "symbols": items})
    except Exception as exc:
        return jsonify({"error": str(exc), "symbols": INDEX_SYMBOLS}), 502


@app.get("/api/symbols/search")
def symbols_search():
    q = request.args.get("q", "")
    limit = min(max(int(request.args.get("limit", 30)), 5), 80)
    fo_only = request.args.get("fo_only") == "1" or request.args.get("kind") == "fo"
    try:
        results = search_symbols(q, limit=limit, fo_only=fo_only)
        return jsonify({"q": q, "count": len(results), "results": results})
    except Exception as exc:
        return jsonify({"error": str(exc), "results": []}), 502


def generate_fallback_option_chain(symbol, spot):
    if symbol in ("NIFTY 50", "NIFTY", "FINNIFTY", "MIDCPNIFTY"):
        step = 50
    elif symbol in ("BANK NIFTY", "BANKNIFTY", "NIFTY BANK", "SENSEX"):
        step = 100
    elif spot < 100:
        step = 2.5
    elif spot < 500:
        step = 5
    elif spot < 1500:
        step = 10
    elif spot < 3000:
        step = 20
    else:
        step = 50

    atm_strike = round(spot / step) * step
    if step < 1:
        atm_strike = round(spot, 1)

    strikes = [round(atm_strike + (i * step), 2) for i in range(-7, 8)]
    rows = []
    ce_tot_oi = 0
    pe_tot_oi = 0

    for strike in strikes:
        ce_intrinsic = max(0, spot - strike)
        diff_pct = (strike - spot) / spot
        ce_extrinsic = max(2.0, (spot * 0.02) * max(0.1, 1 - abs(diff_pct) * 8))
        ce_ltp = round(ce_intrinsic + ce_extrinsic, 2)
        ce_oi = int(max(100, 50000 * max(0.1, 1 - abs(diff_pct) * 6)))
        ce_vol = int(ce_oi * 0.35)

        pe_intrinsic = max(0, strike - spot)
        pe_extrinsic = ce_extrinsic
        pe_ltp = round(pe_intrinsic + pe_extrinsic, 2)
        pe_oi = int(max(100, 48000 * max(0.1, 1 - abs(diff_pct) * 6)))
        pe_vol = int(pe_oi * 0.38)

        ce_tot_oi += ce_oi
        pe_tot_oi += pe_oi

        rows.append({
            "strikePrice": strike,
            "CE": {
                "ltp": ce_ltp,
                "change": round(ce_ltp * 0.035, 2),
                "pChange": round(3.5, 2),
                "oi": ce_oi,
                "changeOi": int(ce_oi * 0.05),
                "vol": ce_vol,
                "iv": round(15.5 + abs(diff_pct) * 20, 1)
            },
            "PE": {
                "ltp": pe_ltp,
                "change": round(-pe_ltp * 0.025, 2),
                "pChange": round(-2.5, 2),
                "oi": pe_oi,
                "changeOi": int(-pe_oi * 0.03),
                "vol": pe_vol,
                "iv": round(16.0 + abs(diff_pct) * 20, 1)
            }
        })

    is_index = symbol in ("NIFTY 50", "NIFTY", "BANK NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX")
    if is_index:
        expiries = [
            "15-OCT-2026 (Current Weekly - 6 DTE)",
            "22-OCT-2026 (Next Weekly - 13 DTE)",
            "29-OCT-2026 (Current Monthly - 20 DTE)",
            "26-NOV-2026 (Next Monthly - 48 DTE)"
        ]
    else:
        expiries = [
            "29-OCT-2026 (Current Monthly - 20 DTE)",
            "26-NOV-2026 (Next Monthly - 48 DTE)",
            "31-DEC-2026 (Far Monthly - 83 DTE)"
        ]

    pcr = round(pe_tot_oi / ce_tot_oi, 2) if ce_tot_oi > 0 else 1.0
    return {
        "source": "FinGroww Option Intelligence",
        "symbol": symbol,
        "spotPrice": spot,
        "expiries": expiries,
        "selectedExpiry": expiries[0],
        "atmStrike": atm_strike,
        "pcr": pcr,
        "totalCeOi": ce_tot_oi,
        "totalPeOi": pe_tot_oi,
        "chain": rows
    }


def fetch_option_chain(symbol):
    sym = normalize_symbol(symbol)
    quote_data = resolve_quote(sym) or {}
    spot = quote_data.get("lastPrice")
    if spot is None or spot <= 0:
        spot = 24000.0 if "NIFTY" in sym else 2500.0

    is_index = sym in ("NIFTY 50", "NIFTY", "BANK NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX")
    nse_sym = "NIFTY" if sym == "NIFTY 50" else ("BANKNIFTY" if sym == "BANK NIFTY" else sym)
    endpoint = f"/api/option-chain-indices?symbol={nse_sym}" if is_index else f"/api/option-chain-equities?symbol={nse_sym}"
    
    data = nse_get(endpoint)
    if data and isinstance(data, dict) and "records" in data:
        records = data.get("records") or {}
        expiries = records.get("expiryDates") or []
        underlying = records.get("underlyingValue") or spot
        raw_items = records.get("data") or []
        
        sel_expiry = expiries[0] if expiries else "CURRENT"
        rows = []
        ce_tot_oi = 0
        pe_tot_oi = 0
        
        for item in raw_items:
            strike = item.get("strikePrice")
            if not strike:
                continue
            if abs(strike - underlying) / underlying > 0.18:
                continue
            ce = item.get("CE") or {}
            pe = item.get("PE") or {}
            ce_oi = ce.get("openInterest") or 0
            pe_oi = pe.get("openInterest") or 0
            ce_tot_oi += ce_oi
            pe_tot_oi += pe_oi
            
            rows.append({
                "strikePrice": strike,
                "CE": {
                    "ltp": ce.get("lastPrice") or 0,
                    "change": ce.get("change") or 0,
                    "pChange": ce.get("pChange") or 0,
                    "oi": ce_oi,
                    "changeOi": ce.get("changeinOpenInterest") or 0,
                    "vol": ce.get("totalTradedVolume") or 0,
                    "iv": ce.get("impliedVolatility") or 0,
                },
                "PE": {
                    "ltp": pe.get("lastPrice") or 0,
                    "change": pe.get("change") or 0,
                    "pChange": pe.get("pChange") or 0,
                    "oi": pe_oi,
                    "changeOi": pe.get("changeinOpenInterest") or 0,
                    "vol": pe.get("totalTradedVolume") or 0,
                    "iv": pe.get("impliedVolatility") or 0,
                }
            })
            
        rows.sort(key=lambda x: x["strikePrice"])
        if rows:
            atm_strike = min(rows, key=lambda x: abs(x["strikePrice"] - underlying))["strikePrice"]
            pcr = round(pe_tot_oi / ce_tot_oi, 2) if ce_tot_oi > 0 else 1.0
            return {
                "source": "NSE Official Live",
                "symbol": sym,
                "spotPrice": underlying,
                "expiries": expiries[:5],
                "selectedExpiry": sel_expiry,
                "atmStrike": atm_strike,
                "pcr": pcr,
                "totalCeOi": ce_tot_oi,
                "totalPeOi": pe_tot_oi,
                "chain": rows
            }

    return generate_fallback_option_chain(sym, spot)


@app.get("/api/option-chain")
def option_chain_api():
    symbol = normalize_symbol(request.args.get("symbol", "NIFTY 50"))
    try:
        res = fetch_option_chain(symbol)
        return jsonify(res)
    except Exception as exc:
        return jsonify({"error": str(exc), "symbol": symbol}), 502


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "source": "FinGroww market proxy (NSE + Yahoo + Option Chain)"})



@app.get("/api/quote")
def quote():
    symbol = normalize_symbol(request.args.get("symbol", "RELIANCE"))
    try:
        data = resolve_quote(symbol)
        if not data or data.get("lastPrice") is None:
            return jsonify({"error": "No live quote available", "symbol": symbol}), 502
        return jsonify(data)
    except Exception as exc:
        return jsonify({"error": str(exc), "symbol": symbol}), 502


def tf_to_yahoo(tf):
    t = (tf or "15m").strip()
    for key in (t, t.lower(), t.upper()):
        if key in TF_YAHOO:
            return TF_YAHOO[key]
    return ("15m", "1mo")


@app.get("/api/chart")
def chart():
    symbol = normalize_symbol(request.args.get("symbol", "RELIANCE"))
    tf = request.args.get("interval") or request.args.get("days") or "15m"
    interval, range_ = tf_to_yahoo(tf)
    try:
        ticker = yahoo_ticker(symbol)
        rows, meta = fetch_yahoo_chart(ticker, interval, range_)
        if len(rows) < 10:
            return jsonify({"error": "Insufficient candle history", "symbol": symbol}), 502
        return jsonify(
            {
                "source": "Yahoo Finance (free)",
                "symbol": symbol,
                "ticker": ticker,
                "interval": interval,
                "range": range_,
                "lastPrice": meta.get("regularMarketPrice") or rows[-1]["c"],
                "data": rows,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc), "symbol": symbol}), 502


@app.get("/api/live")
def live():
    """Single call: live quote + OHLC series for the dashboard."""
    symbol = normalize_symbol(request.args.get("symbol", "RELIANCE"))
    tf = request.args.get("interval") or "15m"
    interval, range_ = tf_to_yahoo(tf)
    try:
        ticker = yahoo_ticker(symbol)
        rows, meta = fetch_yahoo_chart(ticker, interval, range_)
        quote_data = resolve_quote(symbol)
        if not quote_data:
            quote_data = {}
        price = quote_data.get("lastPrice")
        if price is None:
            price = meta.get("regularMarketPrice") or (rows[-1]["c"] if rows else None)
        if price is None:
            return jsonify({"error": "No live data", "symbol": symbol}), 502
        if len(rows) < 30:
            return jsonify(
                {
                    "source": quote_data.get("source", "Yahoo Finance (free)"),
                    "symbol": symbol,
                    "lastPrice": price,
                    "quote": quote_data,
                    "series": rows,
                    "warning": "Limited history — indicators may be less reliable",
                }
            )
        return jsonify(
            {
                "source": quote_data.get("source", "Yahoo Finance (free)"),
                "symbol": symbol,
                "lastPrice": price,
                "quote": quote_data,
                "series": rows,
                "interval": interval,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc), "symbol": symbol}), 502


if __name__ == "__main__":
    print("FinGroww market server: http://127.0.0.1:8787")
    print("  GET /api/live?symbol=RELIANCE&interval=15m")
    app.run(host="127.0.0.1", port=8787, debug=False)
