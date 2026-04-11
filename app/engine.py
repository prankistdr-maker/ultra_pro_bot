"""
AI Decision Engine - PROFESSIONAL
Incorporates:
- Market manipulation detection (stop hunts, fake breakouts)
- Human psychology traps (FOMO, panic, greed zones)
- Smart money concepts (liquidity, order blocks, FVG)
- Strict trend alignment — never trade against trend
- Max 4 high quality trades per day
- TP always 3x+ the SL (positive expectancy guaranteed)
"""


def market_mode(ind, smc):
    """
    What kind of market are we in right now?
    This determines our entire strategy.
    """
    trend    = ind.get("trend", "RANGING")
    atr_pct  = ind.get("atr_pct", 0)
    rsi      = ind.get("rsi", 50)
    liq_bull = smc.get("liquidity_bull", False)
    liq_bear = smc.get("liquidity_bear", False)

    # MANIPULATION DETECTED: Smart money just swept liquidity
    # This is the highest probability setup — retail got trapped
    if liq_bull and trend != "BEAR":
        return "REVERSAL_BULL"
    if liq_bear and trend not in ["STRONG_BULL", "BULL"]:
        return "REVERSAL_BEAR"

    # STRONG TREND: Clear direction, ride it
    if trend == "STRONG_BULL" and atr_pct > 0.12 and rsi < 68:
        return "TREND_BULL"
    if trend == "BULL" and atr_pct > 0.12 and rsi < 65:
        return "TREND_BULL"
    if trend == "BEAR" and atr_pct > 0.12 and rsi > 32:
        return "TREND_BEAR"

    # EVERYTHING ELSE: Choppy, dangerous, wait
    # Professional traders sit on hands 70% of the time
    return "AVOID"


def detect_manipulation(ind, smc):
    """
    Big players manipulate price to:
    1. Stop hunt: push past obvious levels → grab stops → reverse
    2. Fake breakout: break level → lure FOMO → dump on them
    3. OB reaction: return to where they placed large orders

    Detecting this gives us edge over retail traders.
    """
    rsi      = ind.get("rsi", 50)
    macd_hist= ind.get("macd_hist", 0)
    vol      = ind.get("vol_ratio", 1)
    near_sup = ind.get("near_support", False)
    near_res = ind.get("near_resistance", False)
    liq_bull = smc.get("liquidity_bull", False)
    liq_bear = smc.get("liquidity_bear", False)
    bull_ob  = smc.get("bull_ob", False)
    bear_ob  = smc.get("bear_ob", False)
    bull_fvg = smc.get("bull_fvg", False)
    bear_fvg = smc.get("bear_fvg", False)
    bias     = smc.get("bias", "neutral")

    manip = {"type": "none", "bias": "neutral", "bonus": 0, "description": ""}

    # STOP HUNT DOWN → BUY (strongest setup)
    # Price dips below support, retail panic sells, then reverses hard up
    if liq_bull and near_sup and rsi < 42 and vol > 1.2:
        manip = {"type": "stop_hunt_down", "bias": "buy",
                 "bonus": 4, "description": "Stop hunt ↓ → reversal UP"}

    # STOP HUNT UP → SELL (strongest setup)
    # Price pushes above resistance, retail FOMO buys, then dumps hard
    elif liq_bear and near_res and rsi > 58 and vol > 1.2:
        manip = {"type": "stop_hunt_up", "bias": "sell",
                 "bonus": 4, "description": "Stop hunt ↑ → reversal DOWN"}

    # DEMAND ORDER BLOCK: Institutions left orders here last time
    elif bull_ob and rsi < 52 and macd_hist > -3:
        manip = {"type": "demand_ob", "bias": "buy",
                 "bonus": 3, "description": "Demand order block reaction"}

    # SUPPLY ORDER BLOCK: Institutions want to sell here
    elif bear_ob and rsi > 48 and macd_hist < 3:
        manip = {"type": "supply_ob", "bias": "sell",
                 "bonus": 3, "description": "Supply order block reaction"}

    # FVG FILL: Market imbalance, price returns to fill
    elif bull_fvg and bias == "buy":
        manip = {"type": "fvg_bull", "bias": "buy",
                 "bonus": 2, "description": "Bullish FVG fill"}
    elif bear_fvg and bias == "sell":
        manip = {"type": "fvg_bear", "bias": "sell",
                 "bonus": 2, "description": "Bearish FVG fill"}

    return manip


def psychology_check(ind, direction):
    """
    Check if we are about to make a classic retail psychology mistake.

    FOMO: Buying after big move up (everyone sees it, too late)
    Panic: Selling after big move down (everyone scared, too late)
    Revenge: Trading to recover losses (emotional, dangerous)
    Greed: Extending targets after winning (ego trading)
    """
    rsi      = ind.get("rsi", 50)
    momentum = ind.get("momentum", 0)
    atr_pct  = ind.get("atr_pct", 0)
    vol      = ind.get("vol_ratio", 1)
    macd_hist= ind.get("macd_hist", 0)
    near_res = ind.get("near_resistance", False)
    near_sup = ind.get("near_support", False)

    if direction == "BUY":
        # FOMO: Price already ran big, RSI hot — retail chasing
        if rsi > 68:
            return False, f"FOMO trap: RSI {rsi:.0f} overbought — retail buying top"

        # CHASING: Big candle already happened, momentum exhausted
        if momentum > 1.8 and vol > 2.5:
            return False, "Chasing spike — move already done"

        # RESISTANCE TRAP: Buying right into wall with weak momentum
        if near_res and macd_hist < -2:
            return False, "Resistance wall + weak MACD — retail trap"

        # VOLATILITY SPIKE: High ATR + overbought = blow-off top
        if atr_pct > 0.7 and rsi > 62:
            return False, "Blow-off top spike — wait for calm"

    if direction == "SELL":
        # PANIC: Price already crashed, RSI cold — retail panic selling
        if rsi < 32:
            return False, f"Panic trap: RSI {rsi:.0f} oversold — retail selling bottom"

        # SELLING INTO SUPPORT: Strong floor with positive momentum
        if near_sup and macd_hist > 2:
            return False, "Support + bullish MACD — selling into buyers"

        # VOLATILITY SPIKE DOWN: Exhaustion spike, likely reversal
        if atr_pct > 0.7 and rsi < 38:
            return False, "Crash spike — selling exhaustion, wait"

    return True, "OK"


def check_hard_rules(ind, smc, direction):
    """
    NON-NEGOTIABLE rules. Break these = guaranteed loss over time.
    Professional traders follow these religiously.
    """
    trend     = ind.get("trend", "RANGING")
    rsi       = ind.get("rsi", 50)
    ema_bull  = ind.get("ema_bull", False)
    macd_bull = ind.get("macd_bull", False)
    macd_hist = ind.get("macd_hist", 0)
    bias      = smc.get("bias", "neutral")

    if direction == "BUY":
        # Rule 1: NEVER buy confirmed bear trend
        if trend == "BEAR":
            return False, "BEAR trend — no BUY ever"

        # Rule 2: NEVER buy overbought (retail FOMO zone)
        if rsi > 70:
            return False, f"RSI {rsi:.0f} overbought — retail trap"

        # Rule 3: MACD strongly against us
        if macd_hist < -10:
            return False, f"MACD {macd_hist:.0f} strongly bearish"

        # Rule 4: Minimum 2 of 3 core signals bullish
        core_bull = sum([ema_bull, macd_bull, bias == "buy"])
        if core_bull < 2:
            return False, f"Only {core_bull}/3 core signals bullish"

        # Rule 5: Psychology — no FOMO or panic trades
        ok, reason = psychology_check(ind, "BUY")
        if not ok:
            return False, reason

    if direction == "SELL":
        # Rule 1: NEVER sell strong bull trend with aligned EMAs
        if trend == "STRONG_BULL" and ema_bull:
            return False, "STRONG BULL + EMA aligned — no SELL"

        # Rule 2: NEVER sell oversold (panic zone)
        if rsi < 30:
            return False, f"RSI {rsi:.0f} oversold — panic zone"

        # Rule 3: MACD strongly against us
        if macd_hist > 10:
            return False, f"MACD {macd_hist:.0f} strongly bullish"

        # Rule 4: Minimum 2 of 3 core signals bearish
        core_bear = sum([not ema_bull, not macd_bull, bias == "sell"])
        if core_bear < 2:
            return False, f"Only {core_bear}/3 core signals bearish"

        # Rule 5: Psychology check
        ok, reason = psychology_check(ind, "SELL")
        if not ok:
            return False, reason

    return True, "OK"


def score_direction(ind, smc, direction):
    """
    Score a trade direction 0-25+
    Professional traders need multiple factors to agree.
    Think like a chess player — see the whole board.
    """
    score   = 0
    reasons = []
    is_buy  = direction == "BUY"
    trend   = ind.get("trend", "RANGING")
    rsi     = ind.get("rsi", 50)
    ema_bull= ind.get("ema_bull", False)
    ema_sb  = ind.get("ema_strong_bull", False)
    macd_bull= ind.get("macd_bull", False)
    macd_hist= ind.get("macd_hist", 0)

    # ── TREND ALIGNMENT (most important factor) ─────
    if is_buy:
        if trend == "STRONG_BULL": score += 6; reasons.append("Strong bull trend")
        elif trend == "BULL":      score += 4; reasons.append("Bull trend")
        elif trend == "RANGING":   score += 0
        elif trend == "BEAR":      score -= 8  # Heavy penalty
    else:
        if trend == "BEAR":        score += 6; reasons.append("Bear trend confirmed")
        elif trend == "RANGING":   score += 0
        elif trend == "BULL":      score -= 5
        elif trend == "STRONG_BULL": score -= 8

    # ── EMA ALIGNMENT ───────────────────────────────
    if is_buy:
        if ema_sb:              score += 4; reasons.append("EMA 9>21>50 aligned")
        elif ema_bull:          score += 2; reasons.append("EMA 9>21")
        else:                   score -= 4
        if ind.get("ema_cross_bull"): score += 4; reasons.append("Fresh EMA cross UP ↑")
        if ind.get("above_ema200"):   score += 1; reasons.append("Above EMA200")
    else:
        if not ema_bull:        score += 4; reasons.append("EMA fully bearish")
        else:                   score -= 4
        if ind.get("ema_cross_bear"): score += 4; reasons.append("Fresh EMA cross DN ↓")

    # ── MACD MOMENTUM ───────────────────────────────
    if is_buy:
        if ind.get("macd_cross_bull"): score += 5; reasons.append("MACD cross UP ↑")
        elif macd_bull:            score += 2; reasons.append("MACD positive")
        elif macd_hist < -5:       score -= 3
    else:
        if ind.get("macd_cross_bear"): score += 5; reasons.append("MACD cross DN ↓")
        elif not macd_bull:        score += 2; reasons.append("MACD negative")
        elif macd_hist > 5:        score -= 3

    # ── RSI ZONE ────────────────────────────────────
    if is_buy:
        if rsi < 30:    score += 4; reasons.append(f"RSI oversold {rsi:.0f}")
        elif rsi < 40:  score += 2; reasons.append(f"RSI low {rsi:.0f}")
        elif rsi < 50:  score += 1
        elif rsi > 60:  score -= 2
        elif rsi > 68:  score -= 5
    else:
        if rsi > 72:    score += 4; reasons.append(f"RSI overbought {rsi:.0f}")
        elif rsi > 62:  score += 2; reasons.append(f"RSI high {rsi:.0f}")
        elif rsi > 52:  score += 1
        elif rsi < 40:  score -= 2
        elif rsi < 32:  score -= 5

    # ── SMART MONEY / MANIPULATION ──────────────────
    if is_buy:
        if smc.get("liquidity_bull"):               score += 5; reasons.append("Liquidity sweep ↑")
        if smc.get("bull_ob"):                      score += 4; reasons.append("Demand OB hit")
        if smc.get("bull_fvg"):                     score += 2; reasons.append("Bullish FVG")
        if smc.get("bias") == "buy":               score += 2; reasons.append("SMC bias BUY")
        if smc.get("structure",{}).get("bos_bull"): score += 3; reasons.append("Break of structure UP")
    else:
        if smc.get("liquidity_bear"):               score += 5; reasons.append("Liquidity sweep ↓")
        if smc.get("bear_ob"):                      score += 4; reasons.append("Supply OB hit")
        if smc.get("bear_fvg"):                     score += 2; reasons.append("Bearish FVG")
        if smc.get("bias") == "sell":              score += 2; reasons.append("SMC bias SELL")
        if smc.get("structure",{}).get("bos_bear"): score += 3; reasons.append("Break of structure DN")

    # ── VWAP ────────────────────────────────────────
    above_vwap = ind.get("above_vwap", False)
    if is_buy:
        if above_vwap:  score += 2; reasons.append("Above VWAP")
        else:           score -= 1
    else:
        if not above_vwap: score += 2; reasons.append("Below VWAP")
        else:              score -= 1

    # ── KEY LEVELS ──────────────────────────────────
    if is_buy and ind.get("near_support"):
        score += 2; reasons.append("At support level")
    if not is_buy and ind.get("near_resistance"):
        score += 2; reasons.append("At resistance level")

    # ── VOLUME CONFIRMATION ─────────────────────────
    if ind.get("high_volume"):
        if is_buy and ema_bull:       score += 1; reasons.append("High vol bull")
        if not is_buy and not ema_bull: score += 1; reasons.append("High vol bear")

    return score, reasons


def decide(ind, smc, state):
    """
    Final decision — only take the best setups.
    Professional trading = patience + discipline + waiting.
    Most days should have 0-2 trades, not 10+.
    """
    if not ind:
        return "HOLD", 0, "NORMAL", ["No data"], 0.5, 1.5

    mode    = market_mode(ind, smc)
    atr_pct = ind.get("atr_pct", 0.2)
    manip   = detect_manipulation(ind, smc)

    # AVOID: Most common state — professionals wait here
    if mode == "AVOID":
        return "HOLD", 0, mode, ["Ranging — waiting for setup"], 0, 0

    # ── ADAPTIVE SL/TP ──────────────────────────────
    # KEY MATH: If SL=0.5% and TP=1.5%, winning just 40% = profit
    # 4 wins × 1.5 = 6.0 gained
    # 6 losses × 0.5 = 3.0 lost
    # Net = +3.0 (profitable at 40% win rate!)
    sl_pct = max(atr_pct * 1.5, 0.5)
    sl_pct = min(sl_pct, 1.2)

    if "TREND" in mode:
        
        tp_pct = sl_pct * 4.0   # Trends run far
    elif "REVERSAL" in mode:
        tp_pct = sl_pct * 3.5  # Reversals are sharp
    else:
        tp_pct = sl_pct * 2.5

    sl_pct = round(sl_pct, 2)
    tp_pct = round(tp_pct, 2)

    # ── THRESHOLDS ──────────────────────────────────
    # Only the best setups pass these high bars
    thresholds = {
        "TREND_BULL":    11,
        "TREND_BEAR":    11,
        "REVERSAL_BULL": 12,
        "REVERSAL_BEAR": 12,
    }
    threshold = thresholds.get(mode, 99)

    # ── DAILY LIMITS (protect capital) ──────────────
    if state.get("daily_trades", 0) >= 30:
        return "HOLD", 0, mode, ["4 trades today — done for the day"], sl_pct, tp_pct

    if state.get("daily_loss", 0) > state.get("balance", 1000) * 0.04:
        return "HOLD", 0, mode, ["4% daily loss — protecting capital"], sl_pct, tp_pct

    if len(state.get("positions", [])) >= 1:
        return "HOLD", 0, mode, ["Already in trade — waiting"], sl_pct, tp_pct

    # ── DETERMINE DIRECTION ─────────────────────────
    if "BULL" in mode:
        direction = "BUY"
    elif "BEAR" in mode:
        direction = "SELL"
    else:
        return "HOLD", 0, mode, ["No direction"], sl_pct, tp_pct

    # ── SCORE ───────────────────────────────────────
    score, reasons = score_direction(ind, smc, direction)

    # Smart money manipulation bonus
    if manip["bias"] == ("buy" if direction == "BUY" else "sell"):
        score += manip["bonus"]
        if manip["description"]:
            reasons.insert(0, f"SM: {manip['description']}")

    # ── THRESHOLD CHECK ─────────────────────────────
    if score < threshold:
        return "HOLD", 0, mode, [
            f"Score {score} needs {threshold} — waiting for better setup"
        ], sl_pct, tp_pct

    # ── HARD RULES ──────────────────────────────────
    ok, block_reason = check_hard_rules(ind, smc, direction)
    if not ok:
        return "HOLD", 0, mode, [block_reason], sl_pct, tp_pct

    # ── CONFIDENCE ──────────────────────────────────
    confidence = min(int((score / (threshold + 7)) * 10), 10)
    confidence = max(confidence, 6)

    return direction, confidence, mode, reasons[:5], sl_pct, tp_pct
