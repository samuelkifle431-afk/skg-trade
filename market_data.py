"""Market-data adapters. Never substitutes synthetic prices for live data."""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


TIMEFRAMES = {
    "1M": "1min", "5M": "5min", "15M": "15min", "30M": "30min",
    "1H": "1h", "4H": "4h", "1D": "1day", "1W": "1week",
}
BINANCE_INTERVALS = {"1M": "1m", "5M": "5m", "15M": "15m", "30M": "30m", "1H": "1h", "4H": "4h", "1D": "1d", "1W": "1w"}


class MarketDataError(Exception):
    pass


def _get_json(url: str, timeout: int = 12):
    req = Request(url, headers={"User-Agent": "SKG-TRADE-I/0.4", "Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:300]
        raise MarketDataError(f"Market-data provider returned HTTP {exc.code}: {body}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise MarketDataError(f"Could not retrieve live market data: {exc}") from exc


class BinanceSpotProvider:
    name = "binance_spot"

    def candles(self, symbol: str, timeframe: str, limit: int):
        if timeframe not in BINANCE_INTERVALS:
            raise MarketDataError("Unsupported Binance timeframe")
        normalized = re.sub(r"[^A-Z0-9]", "", symbol.upper())
        if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized):
            raise MarketDataError("Use a valid Binance spot symbol, e.g. BTCUSDT")
        query = urlencode({"symbol": normalized, "interval": BINANCE_INTERVALS[timeframe], "limit": limit})
        rows = _get_json(f"https://api.binance.com/api/v3/klines?{query}")
        if not isinstance(rows, list) or not rows:
            raise MarketDataError("No candle data returned for this symbol")
        return [{
            "time": int(row[0]), "open": float(row[1]), "high": float(row[2]),
            "low": float(row[3]), "close": float(row[4]), "volume": float(row[5]),
        } for row in rows]


class TwelveDataProvider:
    name = "twelvedata"

    def candles(self, symbol: str, timeframe: str, limit: int):
        api_key = os.getenv("TWELVEDATA_API_KEY", "").strip()
        if not api_key:
            raise MarketDataError("Twelve Data is not configured. Add TWELVEDATA_API_KEY to backend/.env")
        if timeframe not in TIMEFRAMES:
            raise MarketDataError("Unsupported timeframe")
        query = urlencode({"symbol": symbol.strip().upper(), "interval": TIMEFRAMES[timeframe], "outputsize": limit, "apikey": api_key})
        payload = _get_json(f"https://api.twelvedata.com/time_series?{query}")
        if payload.get("status") == "error" or "values" not in payload:
            message = payload.get("message", "No candle data returned")
            raise MarketDataError(f"Twelve Data: {message}")
        values = list(reversed(payload["values"]))
        candles = []
        for row in values:
            candles.append({
                "time": row.get("datetime"), "open": float(row["open"]),
                "high": float(row["high"]), "low": float(row["low"]),
                "close": float(row["close"]), "volume": float(row.get("volume") or 0),
            })
        return candles


def provider_status():
    return {
        "selection": os.getenv("MARKET_DATA_PROVIDER", "auto").lower(),
        "providers": [
            {"id": "binance_spot", "configured": True, "markets": ["crypto"], "access": "public_spot_data"},
            {"id": "twelvedata", "configured": bool(os.getenv("TWELVEDATA_API_KEY", "").strip()), "markets": ["forex", "gold", "crypto", "indices", "stocks"], "access": "api_key_required; symbol and plan coverage vary"},
        ],
        "live_data_only": True,
        "note": "Provider coverage, delays, rate limits and exchange permissions depend on the provider plan. No demo prices are presented as live.",
    }


def fetch_candles(market: str, symbol: str, timeframe: str, limit: int):
    market = market.lower().strip()
    timeframe = timeframe.upper().strip()
    selection = os.getenv("MARKET_DATA_PROVIDER", "auto").lower().strip()
    if timeframe not in TIMEFRAMES:
        raise MarketDataError(f"Unsupported timeframe. Choose: {', '.join(TIMEFRAMES)}")
    if market not in {"forex", "gold", "crypto", "indices", "stocks"}:
        raise MarketDataError("Unsupported market. Choose forex, gold, crypto, indices or stocks")
    if selection not in {"auto", "binance", "twelvedata"}:
        raise MarketDataError("MARKET_DATA_PROVIDER must be auto, binance or twelvedata")

    if selection == "binance" or (selection == "auto" and market == "crypto"):
        if market != "crypto":
            raise MarketDataError("Binance Spot adapter currently supports crypto only")
        provider = BinanceSpotProvider()
    else:
        provider = TwelveDataProvider()
    return provider.name, provider.candles(symbol, timeframe, limit)
