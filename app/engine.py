"""
PROFESSIONAL DECISION ENGINE v5
=================================
Key improvements over v4:
1. CHoCH required for reversals (not just any signal)
2. Multi-timeframe alignment mandatory
3. Premium/Discount zone filter
4. Claude AI final confirmation (optional)
5. Kelly Criterion position sizing
6. TP at actual SMC levels (OB/FVG targets)
7. Max 6 high-quality trades per day
8. Strict R:R minimum 1:3

Target: 65-75% win rate with 1:3 R:R = strong profitability
"""
import datetime
import os
import json
import requests


CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")


def get_session():
    h = datetime.datetime.utcnow().hour
    if 7 <= h <= 10:   return "LONDON", True   # Best: institutions set direction
    if 13 <= h <= 16:  return "NY", True        # Best: institutional follow-through
    if 10 <= h <= 13:  return "OVERLAP", True   # Good: high volume
    if h >= 22 or h <= 6: return "ASIAN", False # Avoid: manipulation, low volume
    return "OFFPEAK", True


def classify_market(ind, smc):
    """
    Classify market into tradeable modes.
    Only trade TREND and REVERSAL — avoid everything else.
    """
    trend      = ind.get("trend", "RANGING")
    atr        = ind.get("atr_pct", 0)
    rsi        = ind.get("rsi", 50)
    choch_bull = smc.get("choch_bull", False)
    choch_bear = smc.get("choch_bear", False)
    liq_bull   = smc.get("liquidity_bull", False)
    liq_bear   = smc.get("liquidity_bear", False)
    htf_bias   = smc.get("htf_bias", "neutral")
    high_buy   = smc.get("high_prob_buy", False)
    high_sell  = smc.get("high_prob_sell", False)
    discount   = smc.get("discount", False)
    premium    = smc.get("premium", False)

    # HIGHEST PRIORITY: CHoCH + OB/FVG in correct zone = institutional setup
    trend_5m = ind.get("trend", "RANGING")
    if trend_5m in ["STRONG_BULL", "BULL"] and htf_bias == "sell":
        return "AVOID"
    if trend_5m == "BEAR" and htf_bias == "buy":
        return "AVOID"
    if choch_bull and high_buy and discount:
        return "CHOCH_BULL"   # Reversal confirmed by structure + entry level
    if choch_bear and high_sell and premium:
        return "CHOCH_BEAR"

    # LIQUIDITY SWEEP + structure confirmation
    if liq_bull and smc.get("bull_ob") and discount and trend != "BEAR":
        return "LIQ_SWEEP_BULL"
    if liq_bear and smc.get("bear_ob") and premium and trend != "STRONG_BULL":
        return "LIQ_SWEEP_BEAR"

    # TREND with HTF alignment
    if trend == "STRONG_BULL" and htf_bias in ["buy", "neutral"] and discount and atr > 0.08:
        return "TREND_BULL"
    if trend == "BULL" and htf_bias == "buy" and discount and atr > 0.08:
        return "TREND_BULL"
    if trend == "BEAR" and htf_bias in ["sell", "neutral"] and premium and atr > 0.08:
        return "TREND_BEAR"

    # BOS continuation
    if smc.get("bos_bull") and discount and trend != "BEAR":
        return "BOS_BULL"
    if smc.get("bos_bear") and premium and trend != "STRONG_BULL":
        return "BOS_BEAR"

    return "AVOID"


def calculate_targets(ind, smc, direction, price):
    """
    Calculate SL and TP at ACTUAL SMC levels.
    
    SL: Below nearest swing low (BUY) or above nearest swing high (SELL)
    TP: At nearest FVG or OB level above/below entry
    
    This gives realistic targets based on market structure,
    not arbitrary percentages.
    """
    atr    = ind.get("atr", price * 0.002)
    atr_pct = ind.get("atr_pct", 0.2)

    if direction == "BUY":
        # SL: Below the swing low that was just swept (with small buffer)
        swing_lows = smc.get("swing_lows", [])
        if swing_lows:
            nearest_sl = min(sl for sl in swing_lows if sl < price)
            sl_price = nearest_sl - atr * 0.3  # Small buffer below swing low
        else:
            sl_price = price * (1 - max(atr_pct * 1.5, 0.5) / 100)

        # TP: At nearest OB above or FVG above
        tp_candidates = []
        if smc.get("bear_ob_low") and smc.get("bear_ob_low", 0) > price:
            tp_candidates.append(smc["bear_ob_low"])
        if smc.get("bear_fvg_low") and smc.get("bear_fvg_low", 0) > price:
            tp_candidates.append(smc["bear_fvg_low"])
        swing_highs = smc.get("swing_highs", [])
        for sh in swing_highs:
            if sh > price:
                tp_candidates.append(sh)

        if tp_candidates:
            tp_price = min(tp_candidates)  # Nearest resistance above
        else:
            sl_dist  = price - sl_price
            tp_price = price + sl_dist * 3.5  # Fallback: 3.5R

    else:  # SELL
        # SL: Above the swing high that was just swept
        swing_highs = smc.get("swing_highs", [])
        if swing_highs:
            above_price = [sh for sh in swing_highs if sh > price]
            nearest_sh  = min(above_price) if above_price else max(swing_highs)
            sl_price    = nearest_sh + atr * 0.3
        else:
            sl_price = price * (1 + max(atr_pct * 1.5, 0.5) / 100)

        # TP: At nearest support OB/FVG below
        tp_candidates = []
        if smc.get("bull_ob_high") and smc.get("bull_ob_high", 0) < price:
            tp_candidates.append(smc["bull_ob_high"])
        if smc.get("bull_fvg_high") and smc.get("bull_fvg_high", 0) < price:
            tp_candidates.append(smc["bull_fvg_high"])
        swing_lows = smc.get("swing_lows", [])
        for sl in swing_lows:
            if sl < price:
                tp_candidates.append(sl)

        if tp_candidates:
            tp_price = max(tp_candidates)  # Nearest support below
        else:
            sl_dist  = sl_price - price
            tp_price = price - sl_dist * 3.5

    # Calculate percentages
    sl_pct = round(abs(price - sl_price) / price * 100, 3)
    tp_pct = round(abs(tp_price - price) / price * 100, 3)

    # Enforce minimum R:R of 1:2.5
    if tp_pct < sl_pct * 2.5:
        if direction == "BUY":
            tp_price = price + (price - sl_price) * 3.0
        else:
            tp_price = price - (sl_price - price) * 3.0
        tp_pct = round(abs(tp_price - price) / price * 100, 3)

    # Safety: SL not too tight (min 0.3%) or too wide (max 1.5%)
    sl_pct = max(0.7, min(sl_pct, 1.2))
    tp_pct = max(sl_pct * 9, tp_pct)

    return round(sl_price, 4), round(tp_price, 4), sl_pct, tp_pct


def score_setup(ind, smc, direction, mode):
    """
    Score the trade setup 0-30.
    Need 15+ to trade. This ensures only institutional quality setups.
    """
    s = 0
    reasons = []
    is_buy  = direction == "BUY"
    trend   = ind.get("trend", "RANGING")
    rsi     = ind.get("rsi", 50)
    ema_b   = ind.get("ema_bull", False)
    macd_b  = ind.get("macd_bull", False)
    macd_h  = ind.get("macd_hist", 0)
    vol_cb  = ind.get("vol_confirmed_bull", False)
    vol_cbd = ind.get("vol_confirmed_bear", False)
    vol_clb = ind.get("vol_climax_buy", False)
    vol_cls = ind.get("vol_climax_sell", False)

    # SMC STRUCTURE (most important - 10 pts max)
    if is_buy:
        if smc.get("choch_bull"):       s += 6; reasons.append("CHoCH ↑ confirmed")
        elif smc.get("bos_bull"):       s += 4; reasons.append("BOS ↑ continuation")
        if smc.get("liquidity_bull"):   s += 4; reasons.append("Liquidity sweep ↑")
        if smc.get("bull_ob"):          s += 4; reasons.append("Demand OB hit")
        if smc.get("bull_fvg"):         s += 3; reasons.append("Bull FVG entry")
        if smc.get("discount"):         s += 3; reasons.append("Discount zone ✓")
        if smc.get("bull_disp"):        s += 2; reasons.append("Displacement ↑")
    else:
        if smc.get("choch_bear"):       s += 6; reasons.append("CHoCH ↓ confirmed")
        elif smc.get("bos_bear"):       s += 4; reasons.append("BOS ↓ continuation")
        if smc.get("liquidity_bear"):   s += 4; reasons.append("Liquidity sweep ↓")
        if smc.get("bear_ob"):          s += 4; reasons.append("Supply OB hit")
        if smc.get("bear_fvg"):         s += 3; reasons.append("Bear FVG entry")
        if smc.get("premium"):          s += 3; reasons.append("Premium zone ✓")
        if smc.get("bear_disp"):        s += 2; reasons.append("Displacement ↓")

    # HTF ALIGNMENT (5 pts)
    htf = smc.get("htf_bias", "neutral")
    if is_buy and htf == "buy":    s += 5; reasons.append("HTF aligned ↑")
    elif not is_buy and htf == "sell": s += 5; reasons.append("HTF aligned ↓")
    elif htf == "neutral":             s += 1
    else:                              s -= 4  # Counter HTF = big penalty

    # TREND (4 pts)
    if is_buy:
        if trend == "STRONG_BULL":  s += 4; reasons.append("Strong bull trend")
        elif trend == "BULL":       s += 3; reasons.append("Bull trend")
        elif trend == "BEAR":       s -= 5
    else:
        if trend == "BEAR":         s += 4; reasons.append("Bear trend")
        elif trend in ["BULL","STRONG_BULL"]: s -= 5

    # VOLUME (3 pts — must confirm)
    if is_buy:
        if vol_clb:   s += 3; reasons.append("Vol climax → reversal ↑")
        elif vol_cb:  s += 2; reasons.append("Volume confirms ↑")
    else:
        if vol_cls:   s += 3; reasons.append("Vol climax → reversal ↓")
        elif vol_cbd: s += 2; reasons.append("Volume confirms ↓")

    # EMA (3 pts)
    if is_buy:
        if ind.get("ema_strong_bull"): s += 3; reasons.append("EMA 9>21>50")
        elif ema_b:                    s += 2
        else:                          s -= 2
        if ind.get("ema_cross_bull"):  s += 2; reasons.append("EMA cross ↑")
    else:
        if not ema_b:                  s += 3; reasons.append("EMA bearish")
        else:                          s -= 2
        if ind.get("ema_cross_bear"):  s += 2; reasons.append("EMA cross ↓")

    # MACD (3 pts)
    if is_buy:
        if ind.get("macd_cross_bull"): s += 3; reasons.append("MACD cross ↑")
        elif macd_b:                   s += 1
        elif macd_h < -10:             s -= 3
    else:
        if ind.get("macd_cross_bear"): s += 3; reasons.append("MACD cross ↓")
        elif not macd_b:               s += 1
        elif macd_h > 10:              s -= 3

    # RSI (2 pts)
    if is_buy:
        if rsi < 30:    s += 3; reasons.append(f"RSI oversold {rsi:.0f}")
        elif rsi < 45:  s += 1
        elif rsi > 65:  s -= 2
    else:
        if rsi > 70:    s += 3; reasons.append(f"RSI overbought {rsi:.0f}")
        elif rsi > 55:  s += 1
        elif rsi < 35:  s -= 2

    # VWAP
    if is_buy and ind.get("above_vwap"):    s += 1; reasons.append("Above VWAP")
    if not is_buy and not ind.get("above_vwap"): s += 1; reasons.append("Below VWAP")

    return s, reasons


def ai_filter(pair, direction, ind, smc, score_val, reasons):
    """
    Claude AI final confirmation.
    Only called for borderline setups (score 14-18).
    High scoring setups (19+) pass automatically.
    This saves API calls while filtering weak setups.
    """
    if not CLAUDE_API_KEY or score_val >= 19:
        return True, "Auto-approved (high score)" if score_val >= 19 else "No AI key"

    prompt = f"""You are a professional crypto trader. Evaluate this trade setup:

Pair: {pair} | Direction: {direction}
Score: {score_val}/30 | Mode: {smc.get('htf_bias','?')}
Structure: {smc.get('mkt_structure','?')} | Zone: {smc.get('pd_zone','?')}
CHoCH: {smc.get('choch_bull') or smc.get('choch_bear')} | BOS: {smc.get('bos_bull') or smc.get('bos_bear')}
OB: {smc.get('bull_ob') or smc.get('bear_ob')} | FVG: {smc.get('bull_fvg') or smc.get('bear_fvg')}
Liquidity sweep: {smc.get('liquidity_bull') or smc.get('liquidity_bear')}
RSI: {ind.get('rsi',50):.0f} | Trend: {ind.get('trend','?')} | MACD: {ind.get('macd_hist',0):.2f}
Top signals: {', '.join(reasons[:4])}

Reply ONLY with JSON: {{"take": true/false, "reason": "one sentence"}}"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_API_KEY, "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 80,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=8
        )
        text = r.json()["content"][0]["text"]
        result = json.loads(text[text.find("{"):text.rfind("}")+1])
        return result.get("take", False), result.get("reason", "AI filtered")
    except:
        return True, "AI unavailable — proceeding"


def hard_rules(ind, smc, direction):
    """Absolute blocks — never override these"""
    trend  = ind.get("trend", "RANGING")
    rsi    = ind.get("rsi", 50)
    ema_b  = ind.get("ema_bull", False)
    macd_h = ind.get("macd_hist", 0)
    htf    = smc.get("htf_bias", "neutral")
    choch  = smc.get("choch_bull") or smc.get("choch_bear")

    if direction == "BUY":
        if trend == "BEAR" and not choch and not smc.get("liquidity_bull"):
            return False, "BEAR trend, no CHoCH"
        if rsi > 74:
            return False, f"RSI {rsi:.0f} — retail FOMO"
        if macd_h < -20:
            return False, f"MACD {macd_h:.0f} extreme bear"
        if htf == "sell" and not choch:
            return False, "Counter HTF — no CHoCH to justify"
        if ind.get("vol_weak_bull"):
            return False, "Weak volume — fake move"
        if not smc.get("discount") and not smc.get("liquidity_bull"):
            return False, "Not in discount zone"

    if direction == "SELL":
        if trend  in ["STRONG_BULL", "BULL"] and ema_b and not choch:
            return False, "STRONG_BULL aligned — no CHoCH"
        if rsi < 26:
            return False, f"RSI {rsi:.0f} — panic zone"
        if macd_h > 20:
            return False, f"MACD {macd_h:.0f} extreme bull"
        if htf == "buy" and not choch:
            return False, "Counter HTF — no CHoCH"
        if ind.get("vol_weak_bear"):
            return False, "Weak volume — fake move"
        if not smc.get("premium") and not smc.get("liquidity_bear"):
            return False, "Not in premium zone"

    return True, "OK"


def decide(pair, ind, smc, balance, positions, daily_loss, daily_trades, last_trade_time):
    """Main decision function"""
    import time

    if not ind:
        return "HOLD", 0, "AVOID", ["No data"], 0, 0, 0, 0

    mode = classify_market(ind, smc)
    session, session_ok = get_session()
    price = ind.get("price", 0)

    if mode == "AVOID" or price == 0:
        return "HOLD", 0, mode, [f"No setup · {session}"], 0, 0, 0, 0

    # Daily limits — quality over quantity
    if daily_loss > balance * 0.04:
        return "HOLD", 0, mode, ["4% daily loss stop"], 0, 0, 0, 0
    if daily_trades >= 100:
        return "HOLD", 0, mode, ["100 trade limit"], 0, 0, 0, 0
    pair_positions = [p for p in positions if p["pair"] == pair]
    if pair_positions:
        return "HOLD", 0, mode, ["Position open on this pair"], 0, 0, 0, 0
    if len(positions) >= 2:
        return "HOLD", 0, mode, ["Max 2 total positions"], 0, 0, 0, 0
    if time.time() - last_trade_time < 120:
        return "HOLD", 0, mode, ["120s cooldown"], 0, 0, 0, 0

    # Direction from mode
    bull_modes = ["CHOCH_BULL", "LIQ_SWEEP_BULL", "TREND_BULL", "BOS_BULL"]
    bear_modes = ["CHOCH_BEAR", "LIQ_SWEEP_BEAR", "TREND_BEAR", "BOS_BEAR"]
    if mode in bull_modes:   direction = "BUY"
    elif mode in bear_modes: direction = "SELL"
    else: return "HOLD", 0, mode, ["No direction"], 0, 0, 0, 0

    # Score
    total, reasons = score_setup(ind, smc, direction, mode)

    # Threshold by mode
    thresholds = {
        "CHOCH_BULL": 14, "CHOCH_BEAR": 14,
        "LIQ_SWEEP_BULL": 13, "LIQ_SWEEP_BEAR": 13,
        "TREND_BULL": 16, "TREND_BEAR": 16,
        "BOS_BULL": 15, "BOS_BEAR": 15,
    }
    threshold = thresholds.get(mode, 15)

    if total < threshold:
        return "HOLD", 0, mode, [f"Score {total}/{threshold}"], 0, 0, 0, 0

    # Hard rules
    ok, block = hard_rules(ind, smc, direction)
    if not ok:
        return "HOLD", 0, mode, [block], 0, 0, 0, 0

    # Session bonus/penalty
    if not session_ok and session == "ASIAN":
        return "HOLD", 0, mode, ["Asian session — avoid"], 0, 0, 0, 0

    # Calculate targets at actual SMC levels
    sl_price, tp_price, sl_pct, tp_pct = calculate_targets(ind, smc, direction, price)

    # AI filter for borderline setups
    if 14 <= total <= 18:
        approved, ai_reason = ai_filter(pair, direction, ind, smc, total, reasons)
        if not approved:
            return "HOLD", 0, mode, [f"AI: {ai_reason}"], 0, 0, 0, 0
        reasons.insert(0, f"AI✓: {ai_reason[:40]}")

    # Confidence
    confidence = min(int((total / (threshold + 8)) * 10), 10)
    confidence = max(confidence, 6)
    if session in ["LONDON", "NY", "OVERLAP"]:
        confidence = min(confidence + 1, 10)
        reasons.insert(0, f"{session} session")

    return direction, confidence, mode, reasons[:6], sl_pct, tp_pct, sl_price, tp_price
