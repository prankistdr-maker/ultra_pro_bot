import asyncio, aiohttp
from app.state import state, lock, PAIRS

async def _fetch_price(session, pair_key):
    kp = PAIRS[pair_key]["kraken"]
    try:
        async with session.get(f"https://api.kraken.com/0/public/Ticker?pair={kp}",
                               timeout=aiohttp.ClientTimeout(total=5)) as r:
            d = await r.json()
            res = d.get("result", {})
            if res: return float(list(res.values())[0]["c"][0])
    except: pass
    return 0.0

async def _fetch_candles(session, pair_key, interval=5, limit=200):
    kp = PAIRS[pair_key]["kraken"]
    try:
        async with session.get(f"https://api.kraken.com/0/public/OHLC?pair={kp}&interval={interval}",
                               timeout=aiohttp.ClientTimeout(total=10)) as r:
            d = await r.json()
            res = d.get("result", {})
            if not res: return []
            k = [x for x in res.keys() if x != "last"][0]
            return [{"time":int(c[0]),"open":float(c[1]),"high":float(c[2]),
                     "low":float(c[3]),"close":float(c[4]),"volume":float(c[6])} for c in res[k][-limit:]]
    except: return []

async def stream():
    ct = ht = 0
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=20)) as session:
        for pair in PAIRS:
            c5  = await _fetch_candles(session, pair, 5, 200)
            c1h = await _fetch_candles(session, pair, 60, 50)
            with lock:
                state["candles"][pair]    = c5
                state["candles_1h"][pair] = c1h
        with lock: state["feed_status"] = "connected"
        while True:
            try:
                prices = await asyncio.gather(*[_fetch_price(session, p) for p in PAIRS])
                with lock:
                    for i, pair in enumerate(PAIRS):
                        if prices[i] > 0:
                            state["prices"][pair] = prices[i]
                            if state["candles"][pair]:
                                state["candles"][pair][-1]["close"] = prices[i]
                                state["candles"][pair][-1]["high"]  = max(state["candles"][pair][-1]["high"], prices[i])
                                state["candles"][pair][-1]["low"]   = min(state["candles"][pair][-1]["low"],  prices[i])
                ct += 3
                if ct >= 60:
                    for pair in PAIRS:
                        c = await _fetch_candles(session, pair, 5, 200)
                        if c:
                            with lock: state["candles"][pair] = c
                    ct = 0
                ht += 3
                if ht >= 600:
                    for pair in PAIRS:
                        c = await _fetch_candles(session, pair, 60, 50)
                        if c:
                            with lock: state["candles_1h"][pair] = c
                    ht = 0
            except: pass
            await asyncio.sleep(3)
