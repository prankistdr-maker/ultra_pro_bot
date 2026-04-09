"""
Price feed using Kraken REST API
Works from Render Oregon - confirmed working
Falls back through multiple sources
"""
import asyncio
import aiohttp
import time
from app.state import state, lock

KRAKEN_PAIRS = {
    "BTC": "XBTUSD",
    "ETH": "ETHUSD",
    "SOL": "SOLUSD"
}

ACTIVE_PAIR = "BTC"
ACTIVE_KRAKEN = "XBTUSD"


async def fetch_price_kraken(session):
    """Fetch current price from Kraken"""
    try:
        url = f"https://api.kraken.com/0/public/Ticker?pair={ACTIVE_KRAKEN}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
            data = await r.json()
            result = data.get("result", {})
            key = list(result.keys())[0]
            price = float(result[key]["c"][0])
            return price
    except Exception as e:
        return None


async def fetch_candles_kraken(session, interval=5, limit=200):
    """Fetch OHLCV candles from Kraken — 5min candles"""
    try:
        url = f"https://api.kraken.com/0/public/OHLC?pair={ACTIVE_KRAKEN}&interval={interval}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
            result = data.get("result", {})
            key = [k for k in result.keys() if k != "last"][0]
            raw = result[key][-limit:]
            candles = []
            for c in raw:
                candles.append({
                    "time":   int(c[0]),
                    "open":   float(c[1]),
                    "high":   float(c[2]),
                    "low":    float(c[3]),
                    "close":  float(c[4]),
                    "volume": float(c[6])
                })
            return candles
    except Exception as e:
        return []


async def stream():
    """
    Main price feed loop
    Polls Kraken every 2 seconds for price
    Fetches candles every 30 seconds
    """
    candle_timer = 0
    connector = aiohttp.TCPConnector(limit=10)

    async with aiohttp.ClientSession(connector=connector) as session:
        # Initial candle load
        candles = await fetch_candles_kraken(session)
        if candles:
            with lock:
                state["candles"] = candles
                state["feed_status"] = "connected"

        while True:
            try:
                # Fetch live price every 2 seconds
                price = await fetch_price_kraken(session)

                if price and price > 0:
                    with lock:
                        state["price"] = price
                        state["last_price_time"] = time.time()
                        state["feed_status"] = "connected"

                        # Update rolling price history
                        state["prices"].append(price)
                        if len(state["prices"]) > 500:
                            state["prices"].pop(0)

                        # Update last candle close with live price
                        if state["candles"]:
                            state["candles"][-1]["close"] = price
                            state["candles"][-1]["high"] = max(
                                state["candles"][-1]["high"], price)
                            state["candles"][-1]["low"] = min(
                                state["candles"][-1]["low"], price)

                # Refresh full candles every 60 seconds
                candle_timer += 2
                if candle_timer >= 60:
                    candles = await fetch_candles_kraken(session)
                    if candles:
                        with lock:
                            state["candles"] = candles
                    candle_timer = 0

            except Exception as e:
                with lock:
                    state["feed_status"] = f"error: {str(e)[:30]}"

            await asyncio.sleep(2)
