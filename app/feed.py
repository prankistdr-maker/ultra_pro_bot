import asyncio, aiohttp
from app.state import state, lock, PAIRS

async def _price(session, pair):
    kp = PAIRS[pair]["kraken"]
    try:
        async with session.get(f"https://api.kraken.com/0/public/Ticker?pair={kp}",
                               timeout=aiohttp.ClientTimeout(total=5)) as r:
            d = await r.json()
            res = d.get("result", {})
            if res: return float(list(res.values())[0]["c"][0])
    except: pass
    return 0.0

async def _candles(session, pair, interval=5, limit=100):
    kp = PAIRS[pair]["kraken"]
    try:
        async with session.get(
            f"https://api.kraken.com/0/public/OHLC?pair={kp}&interval={interval}",
            timeout=aiohttp.ClientTimeout(total=10)) as r:
            d = await r.json()
            res = d.get("result", {})
            if not res: return []
            k = [x for x in res if x != "last"][0]
            return [{"t":int(c[0]),"o":float(c[1]),"h":float(c[2]),
                     "l":float(c[3]),"c":float(c[4]),"v":float(c[6])}
                    for c in res[k][-limit:]]
    except: return []

async def fetch_news(session):
    try:
        async with session.get("https://api.alternative.me/fng/?limit=1",
                               timeout=aiohttp.ClientTimeout(total=5)) as r:
            d = await r.json()
            fg = int(d["data"][0]["value"])
            lbl = d["data"][0]["value_classification"]
            with lock:
                state["news"]["fg"] = fg
                state["news"]["fg_label"] = lbl
    except: pass

async def stream():
    ct = ht = nt = 0
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=20)) as session:
        for pair in PAIRS:
            c5  = await _candles(session, pair, 5, 100)
            c1h = await _candles(session, pair, 60, 50)
            with lock:
                state["candles"][pair]    = c5
                state["candles_1h"][pair] = c1h
        await fetch_news(session)
        with lock: state["feed_status"] = "connected"
        print("Feed connected")

        while True:
            try:
                prices = await asyncio.gather(*[_price(session, p) for p in PAIRS])
                with lock:
                    for i, pair in enumerate(PAIRS):
                        if prices[i] > 0:
                            state["prices"][pair] = prices[i]
                            if state["candles"][pair]:
                                state["candles"][pair][-1]["c"] = prices[i]
                                state["candles"][pair][-1]["h"] = max(state["candles"][pair][-1]["h"], prices[i])
                                state["candles"][pair][-1]["l"] = min(state["candles"][pair][-1]["l"], prices[i])
                ct += 3
                if ct >= 60:
                    for pair in PAIRS:
                        c = await _candles(session, pair, 5, 100)
                        if c:
                            with lock: state["candles"][pair] = c
                    ct = 0
                ht += 3
                if ht >= 600:
                    for pair in PAIRS:
                        c = await _candles(session, pair, 60, 50)
                        if c:
                            with lock: state["candles_1h"][pair] = c
                    ht = 0
                nt += 3
                if nt >= 300:
                    await fetch_news(session)
                    nt = 0
            except Exception as e:
                print(f"Feed error: {e}")
            await asyncio.sleep(3)
