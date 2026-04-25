"""
AI BRAIN v8 - Free APIs + Strategy Evolution
Primary:  Google Gemini (FREE - aistudio.google.com)
Fallback: Groq LLaMA (FREE - console.groq.com)
Backup:   Claude (if available)
Final:    Strategy evolution engine (always works)

GET FREE KEYS:
- GEMINI_API_KEY: https://aistudio.google.com/app/apikey (free, no CC)
- GROQ_API_KEY:   https://console.groq.com/keys (free, no CC)
"""
import os, json, datetime, requests
from app.indicators import compute

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_KEY   = os.getenv("GROQ_API_KEY", "")
CLAUDE_KEY = os.getenv("CLAUDE_API_KEY", "")


def get_session():
    h = datetime.datetime.utcnow().hour
    if 7  <= h < 10: return "LONDON_OPEN", True
    if 13 <= h < 16: return "NY_OPEN", True
    if 10 <= h < 13: return "OVERLAP", True
    return "AVOID", False


def build_prompt(pair, i5, i1, fg, fg_label, session, balance):
    price = i5.get("price", 0)
    trend_1h = i1.get("trend","?")
    if trend_1h in ["STRONG_BULL","BULL","RANGING_BULL"]: bias = "BULLISH"
    elif trend_1h in ["BEAR","RANGING_BEAR"]: bias = "BEARISH"
    else: bias = "NEUTRAL"

    if fg < 20:   fg_ctx = "EXTREME FEAR — institutions buying, contrarian BUY"
    elif fg < 40: fg_ctx = "FEAR — look for bounce setups"
    elif fg > 80: fg_ctx = "EXTREME GREED — smart money selling, contrarian SELL"
    elif fg > 60: fg_ctx = "GREED — avoid new longs"
    else:         fg_ctx = "NEUTRAL — follow technicals"

    return f"""You are an elite crypto trader (ICT/SMC expert). Decide NOW.

PAIR:{pair} PRICE:${price:,.4f} SESSION:{session} BALANCE:${balance:.4f}
F&G:{fg}/100({fg_label}) → {fg_ctx}

1H BIAS = {bias}
1H: trend={i1.get('trend','?')} ema_bull={i1.get('ema_bull',False)} above_vwap={i1.get('above_vwap',False)} rsi={i1.get('rsi',50)}

5M SIGNALS:
trend={i5.get('trend','?')} zone={i5.get('pd_zone','?')} rsi={i5.get('rsi',50)} macd={i5.get('macd',0):.4f}
above_vwap={i5.get('above_vwap',False)} vol={i5.get('vol_ratio',1):.1f}x atr={i5.get('atr_pct',0):.3f}%
liq_sweep_bull={i5.get('liq_sweep_bull',False)} liq_sweep_bear={i5.get('liq_sweep_bear',False)}
choch_bull={i5.get('choch_bull',False)} choch_bear={i5.get('choch_bear',False)}
fvg_bull={i5.get('fvg_bull',False)} fvg_bear={i5.get('fvg_bear',False)}
ob_bull={i5.get('ob_bull',False)} ob_bear={i5.get('ob_bear',False)}
HH={i5.get('hh',False)} HL={i5.get('hl',False)} LL={i5.get('ll',False)} LH={i5.get('lh',False)}
swing_high=${i5.get('swing_high',0):,.4f} swing_low=${i5.get('swing_low',0):,.4f}
liq_above=${i5.get('liq_above',0):,.4f} liq_below=${i5.get('liq_below',0):,.4f}
atr={i5.get('atr',0):.4f}

RULES:
- BIAS={bias} → ONLY trade in that direction (BULLISH=BUY only, BEARISH=SELL only)
- SL for BUY: below swing_low - 0.3*atr
- SL for SELL: above swing_high + 0.3*atr
- TP1: nearest liq level. TP2: next liq level (min 3x SL distance)
- Confidence 6+ = take the trade. Don't be too strict.
- max leverage 10x

Reply ONLY valid JSON:
{{"action":"BUY","confidence":7,"sl_price":0.0,"tp1_price":0.0,"tp2_price":0.0,"leverage":5,"reasoning":"why","setup_type":"name"}}"""


def _call_gemini(prompt):
    if not GEMINI_KEY: return None
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_KEY}"
        r = requests.post(url, json={"contents":[{"parts":[{"text":prompt}]}],
            "generationConfig":{"temperature":0.2,"maxOutputTokens":400}}, timeout=12)
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        s=text.find("{"); e=text.rfind("}")+1
        return json.loads(text[s:e])
    except Exception as ex:
        print(f"[GEMINI] {ex}")
        return None


def _call_groq(prompt):
    if not GROQ_KEY: return None
    try:
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"},
            json={"model":"llama-3.3-70b-versatile","messages":[{"role":"user","content":prompt}],
                  "temperature":0.2,"max_tokens":400}, timeout=12)
        text = r.json()["choices"][0]["message"]["content"]
        s=text.find("{"); e=text.rfind("}")+1
        return json.loads(text[s:e])
    except Exception as ex:
        print(f"[GROQ] {ex}")
        return None


def _call_claude(prompt):
    if not CLAUDE_KEY: return None
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key":CLAUDE_KEY,"anthropic-version":"2023-06-01","Content-Type":"application/json"},
            json={"model":"claude-haiku-4-5-20251001","max_tokens":400,"messages":[{"role":"user","content":prompt}]},
            timeout=12)
        text = r.json()["content"][0]["text"]
        s=text.find("{"); e=text.rfind("}")+1
        return json.loads(text[s:e])
    except Exception as ex:
        print(f"[CLAUDE] {ex}")
        return None


def _validate(d, i5, i1):
    """Fix all values, prevent TP:undefined bug"""
    if not d: return None
    price = i5.get("price", 0)
    if price <= 0: return None

    action = str(d.get("action","HOLD")).upper()
    if action not in ["BUY","SELL","HOLD"]: action = "HOLD"

    # Hard direction guard
    t1h = i1.get("trend","RANGING_BEAR")
    if action=="SELL" and t1h in ["STRONG_BULL","BULL"] and not i1.get("choch_bear",False):
        print(f"[GUARD] Blocked SELL in {t1h}"); action="HOLD"
    if action=="BUY" and t1h in ["BEAR"] and not i1.get("choch_bull",False):
        print(f"[GUARD] Blocked BUY in {t1h}"); action="HOLD"

    conf = max(1, min(10, int(d.get("confidence", 5))))
    lev  = max(1, min(10, int(d.get("leverage", 5))))
    atr  = i5.get("atr", price*0.002)

    # Safe SL/TP with explicit defaults — fixes TP:undefined
    if action == "BUY":
        sl  = float(d.get("sl_price") or price*(1-max(i5.get("atr_pct",0.5),0.5)/100))
        tp1 = float(d.get("tp1_price") or price*1.012)
        tp2 = float(d.get("tp2_price") or price*1.025)
        if sl  >= price: sl  = i5.get("swing_low", price*0.993) - atr*0.3
        if tp1 <= price: tp1 = price*1.012
        if tp2 <= tp1:   tp2 = tp1*1.015
    elif action == "SELL":
        sl  = float(d.get("sl_price") or price*(1+max(i5.get("atr_pct",0.5),0.5)/100))
        tp1 = float(d.get("tp1_price") or price*0.988)
        tp2 = float(d.get("tp2_price") or price*0.975)
        if sl  <= price: sl  = i5.get("swing_high", price*1.007) + atr*0.3
        if tp1 >= price: tp1 = price*0.988
        if tp2 >= tp1:   tp2 = tp1*0.985
    else:
        sl=tp1=tp2=price

    # Enforce min R:R 2.5
    sl_dist = abs(price-sl)
    if sl_dist > 0 and abs(tp2-price) < sl_dist*2.5:
        tp2 = price + sl_dist*3.0 if action=="BUY" else price - sl_dist*3.0

    return {
        "action":     action,
        "confidence": conf,
        "sl_price":   round(sl,  4),
        "tp1_price":  round(tp1, 4),
        "tp2_price":  round(tp2, 4),
        "leverage":   lev,
        "reasoning":  str(d.get("reasoning","AI decision"))[:200],
        "setup_type": str(d.get("setup_type","AI"))[:60],
        "source":     d.get("_source","ai"),
    }


def ask_ai(pair, i5, i1, news, balance, positions):
    session, tradeable = get_session()
    if not tradeable:
        return {"action":"HOLD","confidence":1,"sl_price":i5.get("price",0),
                "tp1_price":i5.get("price",0),"tp2_price":i5.get("price",0),
                "leverage":1,"reasoning":"Asian session — no trading","setup_type":"WAIT","source":"session"}

    fg = news.get("fg", 50); fg_label = news.get("fg_label","neutral")
    prompt = build_prompt(pair, i5, i1, fg, fg_label, session, balance)

    # Try all AI sources
    for name, fn in [("Gemini",_call_gemini),("Groq",_call_groq),("Claude",_call_claude)]:
        raw = fn(prompt)
        if raw:
            raw["_source"] = name
            d = _validate(raw, i5, i1)
            if d:
                print(f"[{name}] {pair} → {d['action']} {d['confidence']}/10 | {d['setup_type']}")
                return d

    # All APIs failed — strategy engine fallback
    return _strategy_fallback(i5, i1)


def _strategy_fallback(i5, i1):
    """Pure rule-based fallback when all AI unavailable"""
    from app.strategies import get_best_active_strategy, get_strategy_signal, STRATEGY_POOL
    # Try multi-signal as default
    direction, conf = get_strategy_signal("S6_MULTI_SIGNAL", i5, i1)
    if direction == "HOLD":
        direction, conf = get_strategy_signal("S1_LIQ_CHOCH", i5, i1)
    if direction == "HOLD":
        direction, conf = get_strategy_signal("S4_TREND_FOLLOW", i5, i1)

    price = i5.get("price",1); atr = i5.get("atr",price*0.002)

    if direction == "BUY":
        sl  = round(i5.get("swing_low",price*0.993) - atr*0.3, 4)
        tp1 = round(i5.get("liq_above",price*1.012), 4)
        tp2 = round(max(tp1, price*1.025), 4)
        if tp2 <= tp1: tp2 = round(tp1*1.015, 4)
    elif direction == "SELL":
        sl  = round(i5.get("swing_high",price*1.007) + atr*0.3, 4)
        tp1 = round(i5.get("liq_below",price*0.988), 4)
        tp2 = round(min(tp1, price*0.975), 4)
        if tp2 >= tp1: tp2 = round(tp1*0.985, 4)
    else:
        sl=tp1=tp2=price

    return {"action":direction,"confidence":conf,"sl_price":sl,"tp1_price":tp1,"tp2_price":tp2,
            "leverage":5,"reasoning":f"Rule fallback: {direction}","setup_type":"Rules","source":"fallback"}
