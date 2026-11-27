"""
FinGroww SaaS Platform — 3-Timeframe Quantitative Confluence Intelligence Service (Phase 3).
Strict timeframe hierarchy:
  1. 1H Trend Confirmation
  2. 15M Primary Signal
  3. 5M Entry Confirmation
Reports verifiable calculated indicators only (no fabricated price/confidence data).
"""

from typing import Any, Dict, List, Optional


def _ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    k = 2.0 / (period + 1)
    val = sum(values[:period]) / period
    for v in values[period:]:
        val = (v * k) + (val * (1.0 - k))
    return round(val, 2)


def _eval_timeframe_candles(candles: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    closes = [float(c["c"]) for c in candles if isinstance(c, dict) and c.get("c") is not None]
    if len(closes) < 21:
        return {
            "timeframe": label,
            "status": "INSUFFICIENT_CANDLES",
            "candle_count": len(closes),
            "bias": "NEUTRAL",
            "ema9": None,
            "ema21": None,
            "last_close": closes[-1] if closes else None,
        }
    e9 = _ema(closes, 9)
    e21 = _ema(closes, 21)
    last_c = closes[-1]
    if e9 > e21 and last_c >= e9 * 0.999:
        bias = "BULLISH"
    elif e9 < e21 and last_c <= e9 * 1.001:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "timeframe": label,
        "status": "COMPUTED",
        "candle_count": len(closes),
        "bias": bias,
        "ema9": e9,
        "ema21": e21,
        "last_close": round(last_c, 2),
    }


def evaluate_three_timeframe_confluence(
    symbol: str,
    candles_1h: Optional[List[Dict[str, Any]]] = None,
    candles_15m: Optional[List[Dict[str, Any]]] = None,
    candles_5m: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Evaluates 1H Trend -> 15M Primary -> 5M Entry alignment with explicit verification."""
    sym_norm = symbol.strip().upper()
    if candles_1h is None or candles_15m is None or candles_5m is None:
        try:
            import fingroww_market_server as srv
            sym_norm = srv.normalize_symbol(sym_norm)
            if candles_1h is None:
                candles_1h = srv.fetch_chart_rows(sym_norm, "1h", "1mo") or []
            if candles_15m is None:
                candles_15m = srv.fetch_chart_rows(sym_norm, "15m", "5d") or []
            if candles_5m is None:
                candles_5m = srv.fetch_chart_rows(sym_norm, "5m", "2d") or []
        except Exception:
            candles_1h = candles_1h or []
            candles_15m = candles_15m or []
            candles_5m = candles_5m or []

    tf_1h = _eval_timeframe_candles(candles_1h, "1H_TREND_CONFIRMATION")
    tf_15m = _eval_timeframe_candles(candles_15m, "15M_PRIMARY_SIGNAL")
    tf_5m = _eval_timeframe_candles(candles_5m, "5M_ENTRY_CONFIRMATION")

    biases = [tf_1h["bias"], tf_15m["bias"], tf_5m["bias"]]
    computed_all = all(x["status"] == "COMPUTED" for x in (tf_1h, tf_15m, tf_5m))

    bull_count = biases.count("BULLISH")
    bear_count = biases.count("BEARISH")

    if not computed_all:
        verdict = "INSUFFICIENT_DATA"
        alignment_score = 0
    elif bull_count == 3:
        verdict = "STRONG_BUY_CONFLUENCE"
        alignment_score = 3
    elif bear_count == 3:
        verdict = "STRONG_SELL_CONFLUENCE"
        alignment_score = 3
    elif bull_count == 2 and tf_1h["bias"] == "BULLISH":
        verdict = "MODERATE_BUY_SETUP"
        alignment_score = 2
    elif bear_count == 2 and tf_1h["bias"] == "BEARISH":
        verdict = "MODERATE_SELL_SETUP"
        alignment_score = 2
    else:
        verdict = "WAIT_CONSOLIDATION"
        alignment_score = max(bull_count, bear_count)

    return {
        "ok": True,
        "symbol": sym_norm,
        "verdict": verdict,
        "alignment_score": f"{alignment_score}/3",
        "data_verified": computed_all,
        "timeframes": {
            "1h": tf_1h,
            "15m": tf_15m,
            "5m": tf_5m,
        },
    }
