"""
CLAUDE AI TRADING BRAIN
========================
Claude AI makes ALL trading decisions.
No fixed algorithm. Claude receives:
- Real price + candles (5m + 1H)
- All technical indicators computed from real data
- Fear & Greed index
- Current market session
- Account balance and open positions
- Recent trade history

Claude decides: BUY / SELL / HOLD
With exact SL%, TP%, risk% and reasoning.

This is adaptive, psychological, context-aware trading.
Claude has deep knowledge of SMC, ICT, Wyckoff, liquidity,
order blocks, FVG, CHoCH, BOS, premium/discount zones,
market psychology, session analysis, news sentiment.
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
    m = datetime.datetime.utcnow().minute
    if 7  <= h < 10: return "LONDON OPEN (best time - institutions active)"
    if 13 <= h < 16: return "NEW YORK OPEN (best time - high volume)"
    if 10 <= h < 13: return "LONDON/NY OVERLAP (good volume)"
    if 22 <= h or h < 7: return "ASIAN SESSION (low volume - be cautious)"
    return "OFF-PEAK"


def ask_claude(pair, ind5m, ind1h, news, balance, positions, recent_trades):
    """
    Send everything to Claude and let it decide.
    Claude knows SMC, ICT, Wyckoff, psychology, news sentiment.
    Claude adapts dynamically - not a fixed algorithm.
    """
    if not CLAUDE_KEY:
        return rule_based_fallback(ind5m, balance)

    session = get_session()
    fg = news.get("fg", 50)
    fg_label = news.get("fg_label", "neutral")

    # Fear & Greed interpretation
    if fg < 20:
        sentiment_note = "EXTREME FEAR - contrarian BUY opportunity, institutions accumulating"
    elif fg < 40:
        sentiment_note = "FEAR - cautious, look for bounce setups"
    elif fg > 80:
        sentiment_note = "EXTREME GREED - contrarian SELL, distribution phase likely"
    elif fg > 60:
        sentiment_note = "GREED - caution on longs, look for short setups"
    else:
        sentiment_note = "NEUTRAL - trade technicals"

    open_pos = [p for p in positions if p.get("pair") == pair]
    recent = recent_trades[-5:] if recent_trades else []

    prompt = f"""You are an elite crypto trader with deep expertise in:
- ICT (Inner Circle Trader) concepts: liquidity sweeps, order blocks, FVG, CHoCH, BOS
- Wyckoff method: accumulation, distribution, spring, upthrust
- Smart Money Concepts: premium/discount zones, equal highs/lows, displacement
- Market psychology: FOMO, panic, stop hunts, retail traps
- Session analysis: London/NY kill zones, Asian manipulation

You must make a REAL trading decision right now. Be adaptive, not algorithmic.

═══ MARKET DATA: {pair} ═══
Session: {session}

5-MINUTE CHART (entry timeframe):
Price: ${ind5m.get('price', 0):,.4f}
Trend: {ind5m.get('trend', '?')} | Zone: {ind5m.get('pd_zone','?')} ({ind5m.get('zone_pct',0)*100:.0f}% of range)
EMA9: ${ind5m.get('ema9',0):,.2f} | EMA21: ${ind5m.get('ema21',0):,.2f} | EMA50: ${ind5m.get('ema50',0):,.2f}
EMA Bull: {ind5m.get('ema_bull',False)} | Strong Bull: {ind5m.get('ema_strong_bull',False)}
RSI: {ind5m.get('rsi',50)} | MACD: {ind5m.get('macd',0):.4f}
ATR: {ind5m.get('atr_pct',0):.3f}% | VWAP: ${ind5m.get('vwap',0):,.2f} | Above VWAP: {ind5m.get('above_vwap',False)}
Volume ratio: {ind5m.get('vol_ratio',1):.2f}x | High vol: {ind5m.get('high_volume',False)}

SMC SIGNALS:
Liquidity Sweep UP: {ind5m.get('liq_sweep_bull',False)} (price swept below prev low then recovered)
Liquidity Sweep DOWN: {ind5m.get('liq_sweep_bear',False)} (price swept above prev high then fell)
CHoCH Bull: {ind5m.get('choch_bull',False)} | CHoCH Bear: {ind5m.get('choch_bear',False)}
FVG Bull: {ind5m.get('fvg_bull',False)} | FVG Bear: {ind5m.get('fvg_bear',False)}
Order Block Bull: {ind5m.get('ob_bull',False)} | Order Block Bear: {ind5m.get('ob_bear',False)}
Higher Highs: {ind5m.get('hh',False)} | Higher Lows: {ind5m.get('hl',False)}
Lower Lows: {ind5m.get('ll',False)} | Lower Highs: {ind5m.get('lh',False)}
Equal highs nearby: {ind5m.get('eq_highs_count',0)} | Equal lows nearby: {ind5m.get('eq_lows_count',0)}
Prev structure high: ${ind5m.get('prev_high',0):,.2f} | Prev low: ${ind5m.get('prev_low',0):,.2f}
Swing high: ${ind5m.get('swing_high',0):,.2f} | Swing low: ${ind5m.get('swing_low',0):,.2f}

1-HOUR CHART (bias timeframe):
Trend: {ind1h.get('trend','?')} | EMA Bull: {ind1h.get('ema_bull',False)}
RSI: {ind1h.get('rsi',50)} | Above VWAP: {ind1h.get('above_vwap',False)}
CHoCH Bull: {ind1h.get('choch_bull',False)} | CHoCH Bear: {ind1h.get('choch_bear',False)}
Liq Sweep Bull: {ind1h.get('liq_sweep_bull',False)} | Bear: {ind1h.get('liq_sweep_bear',False)}

MARKET SENTIMENT:
Fear & Greed Index: {fg}/100 ({fg_label})
Interpretation: {sentiment_note}

ACCOUNT:
Balance: ${balance:.5f} | Starting: $20.00
Open positions on this pair: {len(open_pos)} | Total positions: {len(positions)}
Daily trades: 0 (no hard limit - trade when you see opportunity)

RECENT TRADES (last 5):
{json.dumps([{k: v for k,v in t.items() if k in ['dir','pnl','reason','pair']} for t in recent], indent=2) if recent else 'None yet - first trades'}

═══ YOUR DECISION ═══
Analyze this like a professional SMC trader would:
1. What is the HTF (1H) bias?
2. What is the 5m setup showing?
3. Is there a liquidity sweep + CHoCH or OB/FVG confluence?
4. Is price in correct premium/discount zone?
5. What does market psychology suggest?
6. What does Fear & Greed suggest?

Consider: On a $20 account, even $0.50 profit is meaningful. Be willing to trade when you see GOOD setups.
Do NOT require perfect conditions - real traders take 60-70% confidence trades.

Respond ONLY with valid JSON:
{{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 1-10,
  "sl_pct": 0.3-1.5,
  "tp_pct": 0.9-5.0,
  "risk_pct": 1-4,
  "reasoning": "2-3 sentence explanation of WHY including SMC context",
  "key_level": "the specific price level that invalidates this trade",
  "setup_type": "e.g. Liquidity sweep + CHoCH, OB retest, FVG fill, BOS continuation"
}}"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=15
        )
        text = r.json()["content"][0]["text"]
        start = text.find("{"); end = text.rfind("}") + 1
        decision = json.loads(text[start:end])

        # Validate
        decision["action"] = decision.get("action", "HOLD").upper()
        if decision["action"] not in ["BUY", "SELL", "HOLD"]:
            decision["action"] = "HOLD"
        decision["confidence"]  = max(1, min(10, int(decision.get("confidence", 5))))
        decision["sl_pct"]      = max(0.3, min(1.5,  float(decision.get("sl_pct", 0.7))))
        decision["tp_pct"]      = max(0.9, min(5.0,  float(decision.get("tp_pct", 2.0))))
        decision["risk_pct"]    = max(1.0, min(4.0,  float(decision.get("risk_pct", 2.0))))

        # Enforce minimum R:R of 2.5
        if decision["tp_pct"] < decision["sl_pct"] * 2.5:
            decision["tp_pct"] = round(decision["sl_pct"] * 3.0, 2)

        print(f"[CLAUDE] {pair} → {decision['action']} conf:{decision['confidence']}/10 | {decision.get('setup_type','')}")
        return decision

    except Exception as e:
        print(f"[CLAUDE] Error: {e}")
        return rule_based_fallback(ind5m, balance)


def rule_based_fallback(ind, balance):
    """Simple fallback when Claude API unavailable"""
    trend = ind.get("trend", "RANGING")
    rsi   = ind.get("rsi", 50)
    ema_b = ind.get("ema_bull", False)
    liq_b = ind.get("liq_sweep_bull", False)
    liq_br= ind.get("liq_sweep_bear", False)
    choch_b = ind.get("choch_bull", False)
    choch_br= ind.get("choch_bear", False)
    atr   = max(ind.get("atr_pct", 0.3), 0.3)

    sl = round(max(atr*1.5, 0.5), 2)
    tp = round(sl * 3.0, 2)

    if (liq_b or choch_b) and trend in ["STRONG_BULL","BULL"] and rsi < 65:
        return {"action":"BUY","confidence":7,"sl_pct":sl,"tp_pct":tp,
                "risk_pct":2,"reasoning":"Rule: Liquidity sweep + bullish CHoCH in uptrend",
                "key_level":str(ind.get("swing_low",0)),"setup_type":"Liq sweep + CHoCH"}

    if (liq_br or choch_br) and trend == "BEAR" and rsi > 35:
        return {"action":"SELL","confidence":7,"sl_pct":sl,"tp_pct":tp,
                "risk_pct":2,"reasoning":"Rule: Liquidity sweep + bearish CHoCH in downtrend",
                "key_level":str(ind.get("swing_high",0)),"setup_type":"Liq sweep + CHoCH"}

    return {"action":"HOLD","confidence":3,"sl_pct":sl,"tp_pct":tp,
            "risk_pct":1,"reasoning":"No clear SMC setup - waiting","key_level":"N/A","setup_type":"WAIT"}
