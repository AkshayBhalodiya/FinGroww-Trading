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
    items = list(INDEX_SYMBOLS)
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
        items.append({"symbol": sym, "name": name, "kind": "equity"})
    items.sort(key=lambda x: (0 if x["kind"] == "index" else 1, x["symbol"]))
    symbols_cache = {"at": now, "items": items}
    return items


def search_symbols(query, limit=40):
    items = load_equity_symbols()
    q = (query or "").strip().lower()
    if not q:
        return items
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
    """Full NSE EQ universe + major indices (cached ~24h)."""
    try:
        items = load_equity_symbols()
        return jsonify({"count": len(items), "symbols": items})
    except Exception as exc:
        return jsonify({"error": str(exc), "symbols": INDEX_SYMBOLS}), 502


@app.get("/api/symbols/search")
def symbols_search():
    q = request.args.get("q", "")
    limit = min(max(int(request.args.get("limit", 30)), 5), 80)
    try:
        results = search_symbols(q, limit=limit)
        return jsonify({"q": q, "count": len(results), "results": results})
    except Exception as exc:
        return jsonify({"error": str(exc), "results": []}), 502


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "source": "FinGroww market proxy (NSE + Yahoo)"})


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
