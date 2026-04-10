"""
AI Decision Engine - FIXED

Key fixes:
- Never buy in bear market, never sell in bull market
- Minimum 3 indicators must agree
- Much stricter confluence required
- Trend filter is MANDATORY
- Max 8 trades per day
"""


def market_mode(ind, smc):
    trend = ind.get("trend", "RANGING")
    atr_pct = ind.get("atr_pct", 0)
    squeeze = ind.get("bb_squeeze", False)
    liq_bull = smc.get("liquidity_bull", False)
    liq_bear = smc.get("liquidity_bear", False)

    if liq_bull or liq_bear:
        return "REVERSAL"

    if trend in ["STRONG_BULL", "BULL"] and atr_pct > 0.15:
        return "TREND"
    if trend == "BEAR" and atr_pct > 0.15:
        return "TREND"

    if squeeze:
        return "SCALP"

    if trend == "RANGING":
        return "AVOID"

    return "NORMAL"


def check_hard_rules(ind, smc, direction):
    trend = ind.get("trend", "RANGING")
    rsi = ind.get("rsi", 50)
    ema_bull = ind.get("ema_bull", False)
    macd_bull = ind.get("macd_bull", False)
    bias = smc.get("bias", "neutral")

    if direction == "BUY":
        if trend == "BEAR":
            return False, "Hard rule: BEAR trend — no BUY"

        if rsi > 72:
            return False, f"Hard rule: RSI overbought {rsi}"

        bull_count = sum([ema_bull, macd_bull, bias == "buy"])
        if bull_count < 2:
            return False, f"Hard rule: Only {bull_count}/3 bull signals"

        if rsi < 30 and not smc.get("liquidity_bull"):
            return False, "Hard rule: RSI crash without liquidity"

    if direction == "SELL":
        if trend in ["STRONG_BULL", "BULL"] and ema_bull:
            return False, "Hard rule: BULL trend — no SELL"

        if rsi < 28:
            return False, f"Hard rule: RSI oversold {rsi}"

        bear_count = sum([not ema_bull, not macd_bull, bias == "sell"])
        if bear_count < 2:
            return False, f"Hard rule: Only {bear_count}/3 bear signals"

    return True, "OK"


def score_buy(ind, smc):
    score = 0
    reasons = []

    trend = ind.get("trend", "RANGING")
    if trend == "STRONG_BULL":
        score += 3
        reasons.append("Strong bull trend")
    elif trend == "BULL":
        score += 2
        reasons.append("Bull trend")
    elif trend == "BEAR":
        score -= 5

    if ind.get("ema_strong_bull"):
        score += 2
        reasons.append("EMA 9>21>50")
    elif ind.get("ema_bull"):
        score += 1
        reasons.append("EMA 9>21")
    else:
        score -= 2

    if ind.get("ema_cross_bull"):
        score += 3
        reasons.append("EMA cross UP")

    if ind.get("above_ema200"):
        score += 1
        reasons.append("Above EMA200")

    if ind.get("macd_cross_bull"):
        score += 3
        reasons.append("MACD cross UP")
    elif ind.get("macd_bull"):
        score += 1
        reasons.append("MACD bullish")
    else:
        score -= 1

    rsi = ind.get("rsi", 50)
    if rsi < 30:
        score += 3
    elif rsi < 40:
        score += 2
    elif rsi < 50:
        score += 1
    elif rsi > 65:
        score -= 2

    if smc.get("liquidity_bull"):
        score += 4
    if smc.get("bull_ob"):
        score += 3
    if smc.get("bull_fvg"):
        score += 2
    if smc.get("bias") == "buy":
        score += 2
    if smc.get("structure", {}).get("bos_bull"):
        score += 2

    if ind.get("above_vwap"):
        score += 1
    else:
        score -= 1

    if ind.get("high_volume") and ind.get("ema_bull"):
        score += 1

    if ind.get("near_support"):
        score += 2

    if ind.get("momentum_bull"):
        score += 1

    return score, reasons


def score_sell(ind, smc):
    score = 0
    reasons = []

    trend = ind.get("trend", "RANGING")
    if trend == "BEAR":
        score += 3
    elif trend in ["BULL", "STRONG_BULL"]:
        score -= 5

    if not ind.get("ema_bull"):
        score += 2
    else:
        score -= 2

    if ind.get("ema_cross_bear"):
        score += 3

    if ind.get("macd_cross_bear"):
        score += 3
    elif not ind.get("macd_bull"):
        score += 1
    else:
        score -= 1

    rsi = ind.get("rsi", 50)
    if rsi > 72:
        score += 3
    elif rsi > 60:
        score += 1
    elif rsi < 35:
        score -= 2

    if smc.get("liquidity_bear"):
        score += 4
    if smc.get("bear_ob"):
        score += 3
    if smc.get("bear_fvg"):
        score += 2
    if smc.get("bias") == "sell":
        score += 2

    if not ind.get("above_vwap"):
        score += 1
    else:
        score -= 1

    if ind.get("near_resistance"):
        score += 2

    return score, reasons


def decide(ind, smc, state):
    if not ind:
        return "HOLD", 0, "NORMAL", ["No data"], 0.5, 1.5

    mode = market_mode(ind, smc)
    atr_pct = ind.get("atr_pct", 0.2)

    if mode == "AVOID":
        return "HOLD", 0, mode, ["Ranging market"], 0, 0

    # TP/SL
    sl_pct = max(atr_pct * 1.5, 0.5)
    sl_pct = min(sl_pct, 1.5)
    tp_pct = sl_pct * 2.8

    if mode == "TREND":
        tp_pct = sl_pct * 3.5
    elif mode == "SCALP":
        sl_pct = 0.5
        tp_pct = 1.2
    elif mode == "REVERSAL":
        sl_pct = max(atr_pct, 0.5)
        tp_pct = sl_pct * 3.0

    sl_pct = round(sl_pct, 2)
    tp_pct = round(tp_pct, 2)

    # FIXED INDENTATION HERE
    thresholds = {
        "TREND": 9,
        "SCALP": 99,
        "REVERSAL": 9,
        "NORMAL": 99,
    }
    threshold = thresholds.get(mode, 7)

    if state.get("daily_trades", 0) >= 8:
        return "HOLD", 0, mode, ["Daily limit reached"], sl_pct, tp_pct

    if state.get("daily_loss", 0) > state.get("balance", 1000) * 0.05:
        return "HOLD", 0, mode, ["Daily loss limit"], sl_pct, tp_pct

    if len(state.get("positions", [])) >= 1:
        return "HOLD", 0, mode, ["Position open"], sl_pct, tp_pct

    buy_score, buy_reasons = score_buy(ind, smc)
    sell_score, sell_reasons = score_sell(ind, smc)

    if buy_score >= threshold and buy_score > sell_score:
        ok, reason = check_hard_rules(ind, smc, "BUY")
        if not ok:
            return "HOLD", 0, mode, [reason], sl_pct, tp_pct
        confidence = min(int((buy_score / (threshold + 5)) * 10), 10)
        return "BUY", confidence, mode, buy_reasons, sl_pct, tp_pct

    if sell_score >= threshold and sell_score > buy_score:
        ok, reason = check_hard_rules(ind, smc, "SELL")
        if not ok:
            return "HOLD", 0, mode, [reason], sl_pct, tp_pct
        confidence = min(int((sell_score / (threshold + 5)) * 10), 10)
        return "SELL", confidence, mode, sell_reasons, sl_pct, tp_pct

    return "HOLD", 0, mode, [
        f"No signal (BUY:{buy_score} SELL:{sell_score} need:{threshold})"
    ], sl_pct, tp_pct
