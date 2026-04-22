"""
CLAUDE AI TRADING BRAIN – STRUCTURE-BASED SL/TP
================================================
- SL at swing points / order blocks
- TP at liquidity pools (equal highs/lows, previous day levels)
- Claude receives full structure context
"""

import os, json, time, datetime, requests

CLAUDE_KEY = os.getenv("CLAUDE_API_KEY", "")


def compute_indicators(candles):
    """Compute all indicators Claude needs from real candles"""
    if not candles or len(candles) < 20:
        return {}

    closes = [c["c"] for c in candles]
    highs  = [c["h"] for c in candles]
    lows   = [c["l"] for c in candles]
    vols   = [c["v"] for c in candles]
    price  = closes[-1]

    def ema(vals, p):
        if len(vals) < p: return vals[-1]
        k = 2/(p+1)
        r = sum(vals[:p])/p
        for v in vals[p:]: r = v*k + r*(1-k)
        return r

    e9  = ema(closes, 9)
    e21 = ema(closes, 21)
    e50 = ema(closes, 50) if len(closes) >= 50 else closes[-1]

    gains = [max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses= [max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag = sum(gains[-14:])/14; al = sum(losses[-14:])/14
    rsi = round(100-(100/(1+ag/al)),1) if al > 0 else 100

    e12 = ema(closes, 12); e26 = ema(closes, 26)
    macd = round(e12 - e26, 4)

    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]),
               abs(lows[i]-closes[i-1])) for i in range(1,len(candles))]
    atr = round(sum(trs[-14:])/14, 4)
    atr_pct = round(atr/price*100, 3)

    typical = [(highs[i]+lows[i]+closes[i])/3 for i in range(len(candles))]
    vol_sum = sum(vols)
    vwap = round(sum(t*v for t,v in zip(typical,vols))/vol_sum, 2) if vol_sum > 0 else price

    avg_vol = sum(vols[-20:])/20
    vol_ratio = round(vols[-1]/avg_vol, 2) if avg_vol > 0 else 1

    swing_high = round(max(highs[-20:]), 2)
    swing_low  = round(min(lows[-20:]),  2)

    prev_high = max(highs[-20:-3])
    prev_low  = min(lows[-20:-3])
    liq_sweep_bull = lows[-1] < prev_low and closes[-1] > prev_low and closes[-1] > closes[-2]
    liq_sweep_bear = highs[-1] > prev_high and closes[-1] < prev_high and closes[-1] < closes[-2]

    sh = max(highs[-8:-2]); sl_lvl = min(lows[-8:-2])
    choch_bull = closes[-1] > sh and closes[-2] <= sh
    choch_bear = closes[-1] < sl_lvl and closes[-2] >= sl_lvl

    fvg_bull = len(candles)>=3 and lows[-1] > highs[-3]
    fvg_bear = len(candles)>=3 and highs[-1] < lows[-3]

    ob_bull = ob_bear = False
    for i in range(len(candles)-5, len(candles)-2):
        if i < 1: continue
        if closes[i] < candles[i]["o"] and closes[i+1] > closes[i]:
            ob_bull = True
        if closes[i] > candles[i]["o"] and closes[i+1] < closes[i]:
            ob_bear = True

    hh = max(highs[-3:]) > max(highs[-6:-3]) if len(highs)>=6 else False
    hl = min(lows[-3:])  > min(lows[-6:-3])  if len(lows)>=6  else False
    ll = min(lows[-3:])  < min(lows[-6:-3])  if len(lows)>=6  else False
    lh = max(highs[-3:]) < max(highs[-6:-3]) if len(highs)>=6 else False

    if hh and hl: trend = "STRONG_BULL"
    elif ll and lh: trend = "BEAR"
    elif e9 > e21:  trend = "BULL"
    else:           trend = "RANGING"

    rng = swing_high - swing_low
    zone_pct = round((price - swing_low)/rng, 2) if rng > 0 else 0.5
    pd_zone = "discount" if zone_pct < 0.45 else ("premium" if zone_pct > 0.55 else "equilibrium")

    eq_highs = [h for h in highs[-20:] if abs(h - highs[-1])/highs[-1] < 0.001]
    eq_lows  = [l for l in lows[-20:]  if abs(l - lows[-1])/lows[-1]   < 0.001]

    # Recent swing points for SL placement
    recent_swing_low = min(lows[-5:]) if len(lows)>=5 else swing_low
    recent_swing_high = max(highs[-5:]) if len(highs)>=5 else swing_high

    # Liquidity targets (previous day high/low approximation)
    liquidity_above = max(highs[-20:-5]) if len(highs)>=20 else swing_high
    liquidity_below = min(lows[-20:-5]) if len(lows)>=20 else swing_low

    return {
        "price": round(price, 4),
        "ema9": round(e9,2), "ema21": round(e21,2), "ema50": round(e50,2),
        "ema_bull": e9 > e21, "ema_strong_bull": e9 > e21 > e50,
        "rsi": rsi, "macd": macd, "atr": atr, "atr_pct": atr_pct,
        "vwap": vwap, "above_vwap": price > vwap,
        "vol_ratio": vol_ratio, "high_volume": vol_ratio > 1.5,
        "swing_high": swing_high, "swing_low": swing_low,
        "recent_swing_low": round(recent_swing_low,2),
        "recent_swing_high": round(recent_swing_high,2),
        "liquidity_above": round(liquidity_above,2),
        "liquidity_below": round(liquidity_below,2),
        "liq_sweep_bull": liq_sweep_bull, "liq_sweep_bear": liq_sweep_bear,
        "choch_bull": choch_bull, "choch_bear": choch_bear,
        "fvg_bull": fvg_bull, "fvg_bear": fvg_bear,
        "ob_bull": ob_bull, "ob_bear": ob_bear,
        "trend": trend, "pd_zone": pd_zone, "zone_pct": zone_pct,
        "hh": hh, "hl": hl, "ll": ll, "lh": lh,
        "eq_highs_count": len(eq_highs), "eq_lows_count": len(eq_lows),
        "support": swing_low, "resistance": swing_high,
        "prev_high": round(prev_high,2), "prev_low": round(prev_low,2),
    }


def get_session():
    h = datetime.datetime.utcnow().hour
    if 7 <= h < 10: return "LONDON_OPEN"
    if 13 <= h < 16: return "NEW_YORK_OPEN"
    if 10 <= h < 13: return "LONDON_NY_OVERLAP"
    return "LOW_VOLUME"


def recommend_leverage(confidence, atr_pct, trend_strength):
    base = 5
    if confidence >= 9 and atr_pct > 0.5: base = 15
    elif confidence >= 8: base = 10
    elif confidence >= 7: base = 7
    elif confidence >= 5: base = 5
    else: base = 3
    if atr_pct > 2.0: base = min(base, 3)
    elif atr_pct > 1.0: base = min(base, 5)
    if trend_strength in ["STRONG_BULL", "BEAR"]:
        base = min(base * 1.5, 20)
    return int(min(base, 50))


def ask_claude(pair, ind5m, ind1h, news, balance, positions, recent_trades):
    if not CLAUDE_KEY:
        return structure_based_fallback(ind5m, ind1h, balance)

    session = get_session()
    if session == "LOW_VOLUME":
        return {"action": "HOLD", "confidence": 1, "reasoning": "Low volume session", "setup_type": "WAIT"}

    fg = news.get("fg", 50)
    if fg < 20: sentiment_note = "EXTREME FEAR - contrarian BUY"
    elif fg < 40: sentiment_note = "FEAR - cautious bounce"
    elif fg > 80: sentiment_note = "EXTREME GREED - contrarian SELL"
    elif fg > 60: sentiment_note = "GREED - caution longs"
    else: sentiment_note = "NEUTRAL"

    prompt = f"""You are an elite SMC/ICT trader. Make a trading decision using **structure-based levels**, not fixed percentages.

**RULES:**
1. Determine 1H bias: BULLISH if trend STRONG_BULL/BULL, above VWAP, no bearish CHoCH.
   BEARISH if trend BEAR, below VWAP, no bullish CHoCH. Else NEUTRAL → HOLD.
2. Only trade in direction of 1H bias.
3. Entry requires at least 2 confluences (liq sweep + CHoCH, OB retest, FVG fill).
4. **SL must be placed beyond a structural level** (recent swing low for longs, swing high for shorts) with a small buffer (0.1-0.2%).
5. **TP1 = first liquidity level** (previous swing high/low or equal highs/lows).
6. **TP2 = next major liquidity pool** (daily high/low or untested swing).
7. Confidence below 5 → HOLD.

**MARKET DATA ({pair})**
Session: {session}
Price: ${ind5m.get('price', 0):,.4f}

**1H BIAS:**
Trend: {ind1h.get('trend','?')} | Above VWAP: {ind1h.get('above_vwap',False)}
CHoCH Bull: {ind1h.get('choch_bull',False)} | Bear: {ind1h.get('choch_bear',False)}

**5M STRUCTURE:**
Liq Sweep Bull: {ind5m.get('liq_sweep_bull',False)} | Bear: {ind5m.get('liq_sweep_bear',False)}
CHoCH Bull: {ind5m.get('choch_bull',False)} | Bear: {ind5m.get('choch_bear',False)}
FVG Bull: {ind5m.get('fvg_bull',False)} | Bear: {ind5m.get('fvg_bear',False)}
OB Bull: {ind5m.get('ob_bull',False)} | Bear: {ind5m.get('ob_bear',False)}
Zone: {ind5m.get('pd_zone','?')} | RSI: {ind5m.get('rsi',50)}
Recent Swing Low: ${ind5m.get('recent_swing_low',0):,.2f} | Recent Swing High: ${ind5m.get('recent_swing_high',0):,.2f}
Liquidity Above: ${ind5m.get('liquidity_above',0):,.2f} | Liquidity Below: ${ind5m.get('liquidity_below',0):,.2f}
ATR: {ind5m.get('atr',0):.4f} ({ind5m.get('atr_pct',0):.3f}%)

Fear & Greed: {fg}/100 - {sentiment_note}

Return JSON with **exact prices**:
{{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 1-10,
  "sl_price": number,        // exact invalidation price (below recent swing low for longs)
  "tp1_price": number,       // first take profit (nearby liquidity)
  "tp2_price": number,       // second take profit (further liquidity)
  "risk_pct": 1-3,           // % of balance to risk (position sizing)
  "leverage": 1-50,
  "reasoning": "Explain: bias, entry trigger, why SL at that level, why TP at those levels",
  "setup_type": "e.g. Liq Sweep + CHoCH into OB"
}}"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 500, "messages": [{"role": "user", "content": prompt}]},
            timeout=15
        )
        text = r.json()["content"][0]["text"]
        start = text.find("{"); end = text.rfind("}") + 1
        decision = json.loads(text[start:end])
        decision["action"] = decision.get("action", "HOLD").upper()
        decision["confidence"] = max(1, min(10, int(decision.get("confidence", 5))))
        decision["risk_pct"] = max(1.0, min(3.0, float(decision.get("risk_pct", 2.0))))
        decision["leverage"] = max(1, min(50, int(decision.get("leverage",
            recommend_leverage(decision["confidence"], ind5m.get("atr_pct",0.5), ind1h.get("trend","RANGING")))))
        # Validate SL/TP prices
        price = ind5m["price"]
        if decision["action"] == "BUY":
            if decision.get("sl_price", 0) >= price:
                decision["sl_price"] = ind5m["recent_swing_low"] * 0.998
            if decision.get("tp1_price", 0) <= price:
                decision["tp1_price"] = ind5m["liquidity_above"]
            if decision.get("tp2_price", 0) <= price:
                decision["tp2_price"] = ind5m["liquidity_above"] * 1.01
        elif decision["action"] == "SELL":
            if decision.get("sl_price", 0) <= price:
                decision["sl_price"] = ind5m["recent_swing_high"] * 1.002
            if decision.get("tp1_price", 0) >= price:
                decision["tp1_price"] = ind5m["liquidity_below"]
            if decision.get("tp2_price", 0) >= price:
                decision["tp2_price"] = ind5m["liquidity_below"] * 0.99
        print(f"[CLAUDE] {pair} → {decision['action']} conf:{decision['confidence']}/10 | SL:${decision.get('sl_price',0):.2f} TP1:${decision.get('tp1_price',0):.2f}")
        return decision
    except Exception as e:
        print(f"[CLAUDE] Error: {e}")
        return structure_based_fallback(ind5m, ind1h, balance)


def structure_based_fallback(ind5m, ind1h, balance):
    """Smart fallback using actual structure levels, not fixed percentages"""
    trend_1h = ind1h.get("trend", "RANGING")
    above_vwap_1h = ind1h.get("above_vwap", False)
    choch_bull_1h = ind1h.get("choch_bull", False)
    choch_bear_1h = ind1h.get("choch_bear", False)

    bias = "NEUTRAL"
    if trend_1h in ["STRONG_BULL", "BULL"] and above_vwap_1h and not choch_bear_1h:
        bias = "BULLISH"
    elif trend_1h == "BEAR" and not above_vwap_1h and not choch_bull_1h:
        bias = "BEARISH"

    liq_bull = ind5m.get("liq_sweep_bull", False)
    liq_bear = ind5m.get("liq_sweep_bear", False)
    choch_bull = ind5m.get("choch_bull", False)
    choch_bear = ind5m.get("choch_bear", False)
    fvg_bull = ind5m.get("fvg_bull", False)
    fvg_bear = ind5m.get("fvg_bear", False)
    ob_bull = ind5m.get("ob_bull", False)
    ob_bear = ind5m.get("ob_bear", False)
    zone = ind5m.get("pd_zone", "equilibrium")
    rsi = ind5m.get("rsi", 50)
    atr = ind5m.get("atr", 0.002 * ind5m["price"])
    price = ind5m["price"]
    swing_low = ind5m["recent_swing_low"]
    swing_high = ind5m["recent_swing_high"]
    liq_above = ind5m["liquidity_above"]
    liq_below = ind5m["liquidity_below"]

    if bias == "BULLISH":
        signals = sum([liq_bull, choch_bull, fvg_bull, ob_bull])
        if signals >= 1 and zone in ["discount", "equilibrium"] and rsi < 70:
            sl_price = swing_low * 0.998  # 0.2% below swing low
            tp1_price = liq_above if liq_above > price * 1.005 else price * 1.01
            tp2_price = max(liq_above, price * 1.02)
            lev = recommend_leverage(6, ind5m.get("atr_pct",0.5), trend_1h)
            return {"action":"BUY","confidence":6,"sl_price":round(sl_price,2),
                    "tp1_price":round(tp1_price,2),"tp2_price":round(tp2_price,2),
                    "risk_pct":2,"leverage":lev,"reasoning":"Structure: SL below swing low, TP at liquidity",
                    "setup_type":"SMC Structure Fallback"}
    elif bias == "BEARISH":
        signals = sum([liq_bear, choch_bear, fvg_bear, ob_bear])
        if signals >= 1 and zone in ["premium", "equilibrium"] and rsi > 30:
            sl_price = swing_high * 1.002  # 0.2% above swing high
            tp1_price = liq_below if liq_below < price * 0.995 else price * 0.99
            tp2_price = min(liq_below, price * 0.98)
            lev = recommend_leverage(6, ind5m.get("atr_pct",0.5), trend_1h)
            return {"action":"SELL","confidence":6,"sl_price":round(sl_price,2),
                    "tp1_price":round(tp1_price,2),"tp2_price":round(tp2_price,2),
                    "risk_pct":2,"leverage":lev,"reasoning":"Structure: SL above swing high, TP at liquidity",
                    "setup_type":"SMC Structure Fallback"}

    return {"action":"HOLD","confidence":3,"reasoning":"No valid structure setup","setup_type":"WAIT"}
