"""
CLAUDE AI TRADING BRAIN – PROFITABILITY OPTIMISED
==================================================
- Strict HTF bias first
- Only trade during high‑volume sessions
- Dynamic leverage based on confidence & volatility
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

    # EMAs
    e9  = ema(closes, 9)
    e21 = ema(closes, 21)
    e50 = ema(closes, 50) if len(closes) >= 50 else closes[-1]

    # RSI
    gains = [max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses= [max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag = sum(gains[-14:])/14; al = sum(losses[-14:])/14
    rsi = round(100-(100/(1+ag/al)),1) if al > 0 else 100

    # MACD
    e12 = ema(closes, 12); e26 = ema(closes, 26)
    macd = round(e12 - e26, 4)

    # ATR
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]),
               abs(lows[i]-closes[i-1])) for i in range(1,len(candles))]
    atr = round(sum(trs[-14:])/14, 4)
    atr_pct = round(atr/price*100, 3)

    # VWAP
    typical = [(highs[i]+lows[i]+closes[i])/3 for i in range(len(candles))]
    vol_sum = sum(vols)
    vwap = round(sum(t*v for t,v in zip(typical,vols))/vol_sum, 2) if vol_sum > 0 else price

    # Volume
    avg_vol = sum(vols[-20:])/20
    vol_ratio = round(vols[-1]/avg_vol, 2) if avg_vol > 0 else 1

    # Swing points (last 20 candles)
    swing_high = round(max(highs[-20:]), 2)
    swing_low  = round(min(lows[-20:]),  2)

    # Liquidity sweep detection
    prev_high = max(highs[-20:-3])
    prev_low  = min(lows[-20:-3])
    liq_sweep_bull = lows[-1] < prev_low and closes[-1] > prev_low and closes[-1] > closes[-2]
    liq_sweep_bear = highs[-1] > prev_high and closes[-1] < prev_high and closes[-1] < closes[-2]

    # CHoCH
    sh = max(highs[-8:-2]); sl_lvl = min(lows[-8:-2])
    choch_bull = closes[-1] > sh and closes[-2] <= sh
    choch_bear = closes[-1] < sl_lvl and closes[-2] >= sl_lvl

    # FVG
    fvg_bull = len(candles)>=3 and lows[-1] > highs[-3]
    fvg_bear = len(candles)>=3 and highs[-1] < lows[-3]

    # OB (last bearish before bullish impulse)
    ob_bull = ob_bear = False
    for i in range(len(candles)-5, len(candles)-2):
        if i < 1: continue
        if closes[i] < candles[i]["o"] and closes[i+1] > closes[i]:
            ob_bull = True
        if closes[i] > candles[i]["o"] and closes[i+1] < closes[i]:
            ob_bear = True

    # Structure
    hh = max(highs[-3:]) > max(highs[-6:-3]) if len(highs)>=6 else False
    hl = min(lows[-3:])  > min(lows[-6:-3])  if len(lows)>=6  else False
    ll = min(lows[-3:])  < min(lows[-6:-3])  if len(lows)>=6  else False
    lh = max(highs[-3:]) < max(highs[-6:-3]) if len(highs)>=6 else False

    if hh and hl: trend = "STRONG_BULL"
    elif ll and lh: trend = "BEAR"
    elif e9 > e21:  trend = "BULL"
    else:           trend = "RANGING"

    # Premium/Discount zone
    rng = swing_high - swing_low
    zone_pct = round((price - swing_low)/rng, 2) if rng > 0 else 0.5
    pd_zone = "discount" if zone_pct < 0.45 else ("premium" if zone_pct > 0.55 else "equilibrium")

    # Equal highs/lows (liquidity pools)
    eq_highs = [h for h in highs[-20:] if abs(h - highs[-1])/highs[-1] < 0.001]
    eq_lows  = [l for l in lows[-20:]  if abs(l - lows[-1])/lows[-1]   < 0.001]

    return {
        "price": round(price, 4),
        "ema9": round(e9,2), "ema21": round(e21,2), "ema50": round(e50,2),
        "ema_bull": e9 > e21, "ema_strong_bull": e9 > e21 > e50,
        "rsi": rsi, "macd": macd, "atr": atr, "atr_pct": atr_pct,
        "vwap": vwap, "above_vwap": price > vwap,
        "vol_ratio": vol_ratio, "high_volume": vol_ratio > 1.5,
        "swing_high": swing_high, "swing_low": swing_low,
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
    if 7  <= h < 10: return "LONDON_OPEN"
    if 13 <= h < 16: return "NEW_YORK_OPEN"
    if 10 <= h < 13: return "LONDON_NY_OVERLAP"
    return "LOW_VOLUME"


def recommend_leverage(confidence, atr_pct, trend_strength):
    """Dynamically adjust leverage based on confidence and volatility"""
    base = 5
    if confidence >= 9 and atr_pct > 0.5:
        base = 15
    elif confidence >= 8:
        base = 10
    elif confidence >= 7:
        base = 7
    else:
        base = 5

    # Reduce leverage in high volatility to avoid liquidation
    if atr_pct > 2.0:
        base = min(base, 3)
    elif atr_pct > 1.0:
        base = min(base, 5)

    # Increase for strong trends
    if trend_strength in ["STRONG_BULL", "BEAR"]:
        base = min(base * 1.5, 20)
    return int(min(base, 50))


def ask_claude(pair, ind5m, ind1h, news, balance, positions, recent_trades):
    if not CLAUDE_KEY:
        return rule_based_fallback(ind5m, ind1h, balance)

    session = get_session()
    if session == "LOW_VOLUME":
        return {"action": "HOLD", "confidence": 1, "reasoning": "Low volume session", "setup_type": "WAIT"}

    fg = news.get("fg", 50)
    fg_label = news.get("fg_label", "neutral")

    if fg < 20: sentiment_note = "EXTREME FEAR - contrarian BUY"
    elif fg < 40: sentiment_note = "FEAR - cautious bounce"
    elif fg > 80: sentiment_note = "EXTREME GREED - contrarian SELL"
    elif fg > 60: sentiment_note = "GREED - caution longs"
    else: sentiment_note = "NEUTRAL"

    open_pos = [p for p in positions if p.get("pair") == pair]

    prompt = f"""You are an elite SMC/ICT trader. Make a decision with strict rules.

**RULES:**
1. 1H bias: BULLISH if trend STRONG_BULL/BULL, above VWAP, no bearish CHoCH.
   BEARISH if trend BEAR, below VWAP, no bullish CHoCH. Else NEUTRAL → HOLD.
2. Only trade in direction of 1H bias.
3. Entry requires at least 2 of: liq sweep + CHoCH, OB retest, FVG fill.
4. Confidence below 7 → HOLD.

SESSION: {session}
1H BIAS: {ind1h.get('trend','?')} | EMA Bull: {ind1h.get('ema_bull',False)} | Above VWAP: {ind1h.get('above_vwap',False)}
5M: LiqSweepBull: {ind5m.get('liq_sweep_bull',False)} | LiqSweepBear: {ind5m.get('liq_sweep_bear',False)}
CHoCH Bull: {ind5m.get('choch_bull',False)} | Bear: {ind5m.get('choch_bear',False)}
FVG Bull: {ind5m.get('fvg_bull',False)} | Bear: {ind5m.get('fvg_bear',False)}
OB Bull: {ind5m.get('ob_bull',False)} | Bear: {ind5m.get('ob_bear',False)}
RSI: {ind5m.get('rsi',50)} | ATR%: {ind5m.get('atr_pct',0)} | Price: ${ind5m.get('price',0):,.4f}
Fear&Greed: {fg}/100 - {sentiment_note}

Return JSON:
{{"action": "BUY"/"SELL"/"HOLD", "confidence": 1-10, "sl_pct": 0.5-1.5, "tp1_pct": 0.9-2.5, "tp2_pct": 2.5-5.0, "risk_pct": 1-3, "leverage": 1-50, "reasoning": "...", "setup_type": "..."}}"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]},
            timeout=15
        )
        text = r.json()["content"][0]["text"]
        start = text.find("{"); end = text.rfind("}") + 1
        decision = json.loads(text[start:end])
        decision["action"] = decision.get("action", "HOLD").upper()
        decision["confidence"] = max(1, min(10, int(decision.get("confidence", 5))))
        decision["sl_pct"] = max(0.5, min(1.5, float(decision.get("sl_pct", 0.8))))
        decision["tp1_pct"] = max(0.9, min(2.5, float(decision.get("tp1_pct", 1.5))))
        decision["tp2_pct"] = max(2.5, min(5.0, float(decision.get("tp2_pct", 3.5))))
        decision["risk_pct"] = max(1.0, min(3.0, float(decision.get("risk_pct", 2.0))))
        decision["leverage"] = max(1, min(50, int(decision.get("leverage", recommend_leverage(decision["confidence"], ind5m.get("atr_pct",0.5), ind1h.get("trend","RANGING")))))
        avg_tp = (decision["tp1_pct"] + decision["tp2_pct"]) / 2
        if avg_tp < decision["sl_pct"] * 2.5:
            decision["tp2_pct"] = round(decision["sl_pct"] * 3.5, 2)
        return decision
    except Exception as e:
        print(f"[CLAUDE] Error: {e}")
        return rule_based_fallback(ind5m, ind1h, balance)


def rule_based_fallback(ind5m, ind1h, balance):
    """Strict fallback — only trades when both 1H and 5m align perfectly"""
    # 1H bias strict check
    trend_1h = ind1h.get("trend", "RANGING")
    above_vwap_1h = ind1h.get("above_vwap", False)
    choch_bull_1h = ind1h.get("choch_bull", False)
    choch_bear_1h = ind1h.get("choch_bear", False)
    liq_bull_1h = ind1h.get("liq_sweep_bull", False)
    liq_bear_1h = ind1h.get("liq_sweep_bear", False)

    bias = "NEUTRAL"
    if trend_1h in ["STRONG_BULL", "BULL"] and above_vwap_1h and not choch_bear_1h and not liq_bear_1h:
        bias = "BULLISH"
    elif trend_1h == "BEAR" and not above_vwap_1h and not choch_bull_1h and not liq_bull_1h:
        bias = "BEARISH"

    # 5m signals
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
    atr_pct = max(ind5m.get("atr_pct", 0.5), 0.5)

    # Only trade if 5m signal count >=2 and correct zone
    if bias == "BULLISH":
        signals = sum([liq_bull, choch_bull, fvg_bull, ob_bull])
        correct_zone = zone in ["discount", "equilibrium"]
        if signals >= 2 and correct_zone and rsi < 65 and atr_pct >= 0.25:
            sl = round(atr_pct * 1.8, 2)
            tp1 = round(sl * 1.2, 2)
            tp2 = round(sl * 3.5, 2)
            lev = recommend_leverage(7, atr_pct, trend_1h)
            return {"action":"BUY","confidence":7,"sl_pct":sl,"tp1_pct":tp1,"tp2_pct":tp2,
                    "risk_pct":2,"leverage":lev,"reasoning":"Fallback: Strong bullish confluence",
                    "invalidation_price":ind5m.get("swing_low",0),"setup_type":"SMC Fallback"}
    elif bias == "BEARISH":
        signals = sum([liq_bear, choch_bear, fvg_bear, ob_bear])
        correct_zone = zone in ["premium", "equilibrium"]
        if signals >= 2 and correct_zone and rsi > 35 and atr_pct >= 0.25:
            sl = round(atr_pct * 1.8, 2)
            tp1 = round(sl * 1.2, 2)
            tp2 = round(sl * 3.5, 2)
            lev = recommend_leverage(7, atr_pct, trend_1h)
            return {"action":"SELL","confidence":7,"sl_pct":sl,"tp1_pct":tp1,"tp2_pct":tp2,
                    "risk_pct":2,"leverage":lev,"reasoning":"Fallback: Strong bearish confluence",
                    "invalidation_price":ind5m.get("swing_high",0),"setup_type":"SMC Fallback"}

    return {"action":"HOLD","confidence":3,"reasoning":"No HTF alignment or insufficient signals","setup_type":"WAIT"}
