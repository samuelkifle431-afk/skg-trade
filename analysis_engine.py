"""Transparent, rule-based OHLC analysis. Not an AI model or a live data feed."""
from __future__ import annotations
from math import isfinite
from typing import Any


def _ema(values: list[float], period: int) -> float:
    alpha = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = alpha * value + (1 - alpha) * result
    return result


def _rsi(closes: list[float], period: int = 14) -> float:
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(x, 0.0) for x in changes]
    losses = [max(-x, 0.0) for x in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def analyze_ohlc(candles: list[dict[str, Any]], instrument: str, timeframe: str, risk_percent: float = 1.0) -> dict[str, Any]:
    if len(candles) < 50:
        raise ValueError("At least 50 candles are required for this analysis")
    if len(candles) > 500:
        raise ValueError("A maximum of 500 candles is allowed")
    for i, c in enumerate(candles):
        vals = [c[k] for k in ("open", "high", "low", "close", "volume")]
        if not all(isfinite(float(v)) for v in vals):
            raise ValueError(f"Candle {i} contains a non-finite number")
        if c["high"] < max(c["open"], c["close"], c["low"]) or c["low"] > min(c["open"], c["close"], c["high"]):
            raise ValueError(f"Candle {i} has invalid OHLC values")
        if c["volume"] < 0:
            raise ValueError(f"Candle {i} has negative volume")

    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    ema20, ema50 = _ema(closes, 20), _ema(closes, 50)
    rsi = _rsi(closes)
    tr = []
    for i, c in enumerate(candles):
        prev = closes[i - 1] if i else float(c["close"])
        tr.append(max(float(c["high"]) - float(c["low"]), abs(float(c["high"]) - prev), abs(float(c["low"]) - prev)))
    atr = sum(tr[-14:]) / 14
    last = closes[-1]
    recent_high, recent_low = max(highs[-20:]), min(lows[-20:])
    bullish = last > ema20 and ema20 > ema50 and rsi >= 52
    bearish = last < ema20 and ema20 < ema50 and rsi <= 48
    if bullish:
        direction, bias = "BUY", "Bullish"
        entry, sl = last, last - 1.5 * atr
        tp1, tp2, tp3 = last + 1.5 * atr, last + 3 * atr, last + 4.5 * atr
        reasons = ["Price is above EMA20", "EMA20 is above EMA50", "RSI supports bullish momentum"]
    elif bearish:
        direction, bias = "SELL", "Bearish"
        entry, sl = last, last + 1.5 * atr
        tp1, tp2, tp3 = last - 1.5 * atr, last - 3 * atr, last - 4.5 * atr
        reasons = ["Price is below EMA20", "EMA20 is below EMA50", "RSI supports bearish momentum"]
    else:
        direction, bias = "WAIT", "Neutral / mixed"
        entry = sl = tp1 = tp2 = tp3 = None
        reasons = ["EMA, price and RSI conditions are not aligned", "Wait for clearer confirmation"]
    # This is a rule-alignment score, not a calibrated probability of success.
    score = sum([last > ema20 if direction == "BUY" else last < ema20 if direction == "SELL" else False,
                 ema20 > ema50 if direction == "BUY" else ema20 < ema50 if direction == "SELL" else False,
                 rsi >= 52 if direction == "BUY" else rsi <= 48 if direction == "SELL" else False])
    confidence = 35 + score * 15 if direction != "WAIT" else 30
    rr = {"tp1": 1.0, "tp2": 2.0, "tp3": 3.0} if direction != "WAIT" else None
    return {
        "instrument": instrument, "timeframe": timeframe, "bias": bias, "signal": direction,
        "entry": round(entry, 8) if entry is not None else None,
        "stop_loss": round(sl, 8) if sl is not None else None,
        "take_profits": {"tp1": round(tp1, 8), "tp2": round(tp2, 8), "tp3": round(tp3, 8)} if tp1 is not None else None,
        "risk_reward": rr, "confidence_score": confidence,
        "confidence_note": "Rule-alignment score only; not a win probability.",
        "indicators": {"ema20": round(ema20, 8), "ema50": round(ema50, 8), "rsi14": round(rsi, 2), "atr14": round(atr, 8)},
        "reference_levels": {"recent_20_candle_high": round(recent_high, 8), "recent_20_candle_low": round(recent_low, 8)},
        "risk_guideline_percent": risk_percent,
        "reasons": reasons,
        "limitations": ["Rule-based OHLC analysis only; no AI vision or live feed is connected.", "No order is placed. Confirm signals independently and account for spread, slippage and fees.", "A 1% risk guideline does not calculate broker-specific lot size or guarantee a maximum loss."],
    }
