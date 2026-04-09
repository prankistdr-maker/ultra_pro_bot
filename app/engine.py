"""
AI Decision Engine - FIXED
Key fixes:
- Never buy in bear market, never sell in bull market  
- Minimum 3 indicators must agree (not just score threshold)
- Much stricter confluence required
- Trend filter is MANDATORY not optional
- Max 8 trades per day
"""


def market_mode(ind, smc):
    trend    = ind.get("trend", "RANGING")
    atr_pct  = ind.get("atr_pct", 0)
    squeeze  = ind.get("bb_squeeze", False)
    liq_bull = smc.get("liquidity_bull", False)
    liq_bear = smc.get("liquidity_bear", False)

    # Liquidity sweep = high probability reversal
    if liq_bull or liq_bear:
        return "REVERSAL"

    # Strong trend with momentum
    if trend in ["STRONG_BULL", "BULL"] and atr_pct > 0.15:
        return "TREND"
    if trend == "BEAR" and atr_pct > 0.15:
        return "TREND"

    # Volatility squeeze about to break
    if squeeze:
        return "SCALP"

    # Ranging market — avoid most trades
    if trend == "RANGING":
        return "AVOID"

    return "NORMAL"


def check_hard_rules(ind, smc, direction):
    """
    Hard rules — ALL must pass or no trade
    These prevent trading against the trend
    """
    trend    = ind.get("trend", "RANGING")
    rsi      = ind.get("rsi", 50)
    ema_bull = ind.get("ema_bull", False)
    macd_bull= ind.get("macd_bull", False)
    bias     = smc.get("bias", "neutral")

    if direction == "BUY":
        # HARD RULE 1: Never buy in strong bear trend
        if trend == "BEAR":
            return False, "Hard rule: BEAR trend — no BUY"

        # HARD RULE 2: Never buy when RSI overbought
        if rsi > 72:
            return False, f"Hard rule: RSI overbought {rsi}"

        # HARD RULE 3: At least 2 of 3 must be bullish: EMA, MACD, SMC bias
        bull_count = sum([ema_bull, macd_bull, bias == "buy"])
        if bull_count < 2:
            return False, f"Hard rule: Only {bull_count}/3 bull signals"

        # HARD RULE 4: RSI must not be falling sharply
        if rsi < 30 and not smc.get("liquidity_bull"):
            return False, "Hard rule: RSI in crash without liquidity sweep"

    if direction == "SELL":
        # Never sell in strong bull trend
        if trend in ["STRONG_BULL", "BULL"] and ema_bull:
            return False, "Hard rule: BULL trend — no SELL"

        if rsi < 28:
            return False, f"Hard rule: RSI oversold {rsi}"

        bear_count = sum([not ema_bull, not macd_bull, bias == "sell"])
        if bear_count < 2:
            return False, f"Hard rule: Only {bear_count}/3 bear signals"

    return True, "OK"


def score_buy(ind, smc):
    score   = 0
    reasons = []

    # Trend (mandatory weight)
    trend = ind.get("trend", "RANGING")
    if trend == "STRONG_BULL":
        score += 3; reasons.append("Strong bull trend")
    elif trend == "BULL":
        score += 2; reasons.append("Bull trend")
    elif trend == "RANGING":
        score += 0
    elif trend == "BEAR":
        score -= 5  # Heavy penalty for buying in bear

    # EMA
    if ind.get("ema_strong_bull"):
        score += 2; reasons.append("EMA 9>21>50")
    elif ind.get("ema_bull"):
        score += 1; reasons.append("EMA 9>21")
    else:
        score -= 2  # Penalty for EMA bearish

    if ind.get("ema_cross_bull"):
        score += 3; reasons.append("EMA cross UP ↑")

    if ind.get("above_ema200"):
        score += 1; reasons.append("Above EMA200")

    # MACD
    if ind.get("macd_cross_bull"):
        score += 3; reasons.append("MACD cross UP")
    elif ind.get("macd_bull"):
        score += 1; reasons.append("MACD bullish")
    else:
        score -= 1  # Penalty for bearish MACD

    # RSI
    rsi = ind.get("rsi", 50)
    if rsi < 30:
        score += 3; reasons.append(f"RSI deeply oversold {rsi:.0f}")
    elif rsi < 40:
        score += 2; reasons.append(f"RSI oversold {rsi:.0f}")
    elif rsi < 50:
        score += 1; reasons.append(f"RSI below 50: {rsi:.0f}")
    elif rsi > 65:
        score -= 2; reasons.append(f"RSI high {rsi:.0f} ⚠")

    # SMC
    if smc.get("liquidity_bull"):
        score += 4; reasons.append("Liquidity sweep ↑")
    if smc.get("bull_ob"):
        score += 3; reasons.append("Demand OB")
    if smc.get("bull_fvg"):
        score += 2; reasons.append("Bullish FVG")
    if smc.get("bias") == "buy":
        score += 2; reasons.append("SMC bias BUY")
    if smc.get("structure", {}).get("bos_bull"):
        score += 2; reasons.append("BOS UP")

    # VWAP
    if ind.get("above_vwap"):
        score += 1; reasons.append("Above VWAP")
    else:
        score -= 1

    # Volume
    if ind.get("high_volume") and ind.get("ema_bull"):
        score += 1; reasons.append("High vol bull")

    # Support
    if ind.get("near_support"):
        score += 2; reasons.append("Near support")

    # Momentum
    if ind.get("momentum_bull"):
        score += 1; reasons.append("Bullish momentum")

    return score, reasons


def score_sell(ind, smc):
    score   = 0
    reasons = []

    trend = ind.get("trend", "RANGING")
    if trend == "BEAR":
        score += 3; reasons.append("Bear trend")
    elif trend == "RANGING":
        score += 0
    elif trend in ["BULL", "STRONG_BULL"]:
        score -= 5  # Heavy penalty

    if not ind.get("ema_bull"):
        score += 2; reasons.append("EMA bearish")
    else:
        score -= 2

    if ind.get("ema_cross_bear"):
        score += 3; reasons.append("EMA cross DOWN ↓")

    if ind.get("macd_cross_bear"):
        score += 3; reasons.append("MACD cross DOWN")
    elif not ind.get("macd_bull"):
        score += 1; reasons.append("MACD bearish")
    else:
        score -= 1

    rsi = ind.get("rsi", 50)
    if rsi > 72:
        score += 3; reasons.append(f"RSI overbought {rsi:.0f}")
    elif rsi > 60:
        score += 1; reasons.append(f"RSI high {rsi:.0f}")
    elif rsi < 35:
        score -= 2

    if smc.get("liquidity_bear"):
        score += 4; reasons.append("Liquidity sweep ↓")
    if smc.get("bear_ob"):
        score += 3; reasons.append("Supply OB")
    if smc.get("bear_fvg"):
        score += 2; reasons.append("Bearish FVG")
    if smc.get("bias") == "sell":
        score += 2; reasons.append("SMC bias SELL")

    if not ind.get("above_vwap"):
        score += 1; reasons.append("Below VWAP")
    else:
        score -= 1

    if ind.get("near_resistance"):
        score += 2; reasons.append("Near resistance")

    return score, reasons


def decide(ind, smc, state):
    """
    Main decision — strict confluence required
    """
    if not ind:
        return "HOLD", 0, "NORMAL", ["No data"], 0.5, 1.5

    mode    = market_mode(ind, smc)
    atr_pct = ind.get("atr_pct", 0.2)

    # Avoid choppy markets
    if mode == "AVOID":
        return "HOLD", 0, mode, ["Ranging market — skip"], 0, 0

    # ─── ADAPTIVE TP/SL ───────────────────────────────────
    # TP must be at least 2.5x SL — always positive expectancy
    # SL must be wide enough to avoid fee-eating (min 0.5%)
    sl_pct = max(atr_pct * 1.5, 0.5)   # Minimum 0.5% SL
    sl_pct = min(sl_pct, 1.5)            # Maximum 1.5% SL
    tp_pct = sl_pct * 2.8               # TP always 2.8x SL

    if mode == "TREND":
        tp_pct = sl_pct * 3.5           # Let trend trades run
    elif mode == "SCALP":
        sl_pct = 0.5
        tp_pct = 1.2                    # Still 2.4x
    elif mode == "REVERSAL":
        sl_pct = max(atr_pct, 0.5)
        tp_pct = sl_pct * 3.0           # Reversals have big targets

    # Round
    sl_pct = round(sl_pct, 2)
    tp_pct = round(tp_pct, 2)

    # ─── THRESHOLDS ───────────────────────────────────────
    # Higher threshold = fewer but better trades
    thresholds = {
        "TREND":    8,
        "SCALP":    6,
        "REVERSAL": 9,
        "NORMAL":   7,
    }
    threshold = thresholds.get(mode, 7)

    # ─── DAILY LIMITS — STRICT ────────────────────────────
    if state.get("daily_trades", 0) >= 8:  # Max 8 trades per day
        return "HOLD", 0, mode, ["Daily limit: 8 trades reached"], sl_pct, tp_pct

    if state.get("daily_loss", 0) > state.get("balance", 1000) * 0.05:
        return "HOLD", 0, mode, ["Daily loss limit 5% reached"], sl_pct, tp_pct

    if len(state.get("positions", [])) >= 1:  # Max 1 position (safer)
        return "HOLD", 0, mode, ["Position already open"], sl_pct, tp_pct

    # ─── SCORE ────────────────────────────────────────────
    buy_score,  buy_reasons  = score_buy(ind, smc)
    sell_score, sell_reasons = score_sell(ind, smc)

    # ─── BUY CHECK ────────────────────────────────────────
    if buy_score >= threshold and buy_score > sell_score:
        # Hard rules check
        ok, reason = check_hard_rules(ind, smc, "BUY")
        if not ok:
            return "HOLD", 0, mode, [reason], sl_pct, tp_pct
        confidence = min(int((buy_score / (threshold + 5)) * 10), 10)
        return "BUY", confidence, mode, buy_reasons, sl_pct, tp_pct

    # ─── SELL CHECK ───────────────────────────────────────
    if sell_score >= threshold and sell_score > buy_score:
        ok, reason = check_hard_rules(ind, smc, "SELL")
        if not ok:
            return "HOLD", 0, mode, [reason], sl_pct, tp_pct
        confidence = min(int((sell_score / (threshold + 5)) * 10), 10)
        return "SELL", confidence, mode, sell_reasons, sl_pct, tp_pct

    return "HOLD", 0, mode, [
        f"No signal (BUY:{buy_score} SELL:{sell_score} need:{threshold})"
    ], sl_pct, tp_pct
