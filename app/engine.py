"""
AI Decision Engine
Multi-factor confluence scoring system
Only trades when multiple signals align
"""


def market_mode(ind, smc):
    """
    Determine market mode:
    - TREND: strong directional move, ride momentum
    - SCALP: tight range, quick in/out
    - REVERSAL: key level hit, fade the move
    - AVOID: choppy/dangerous — stay out
    """
    trend = ind.get("trend", "RANGING")
    atr_pct = ind.get("atr_pct", 0)
    bb_squeeze = ind.get("bb_squeeze", False)
    bias = smc.get("bias", "neutral")

    # High volatility with clear trend = TREND mode
    if trend in ["STRONG_BULL", "BULL"] and atr_pct > 0.15 and bias == "buy":
        return "TREND"

    if trend == "BEAR" and atr_pct > 0.15 and bias == "sell":
        return "TREND"

    # Squeeze about to break = SCALP
    if bb_squeeze and atr_pct < 0.1:
        return "SCALP"

    # Liquidity swept = REVERSAL setup
    if smc.get("liquidity_bull") or smc.get("liquidity_bear"):
        return "REVERSAL"

    # Choppy = avoid
    if trend == "RANGING" and not bb_squeeze:
        return "AVOID"

    return "NORMAL"


def score_buy(ind, smc):
    """
    Score bullish signals — each adds to confluence
    Returns (score, reasons)
    """
    score = 0
    reasons = []

    # ─── TREND (weight: 3) ─────────────────────────────
    if ind.get("trend") == "STRONG_BULL":
        score += 3
        reasons.append("Strong bull trend")
    elif ind.get("trend") == "BULL":
        score += 2
        reasons.append("Bull trend")

    # ─── EMA (weight: 2) ───────────────────────────────
    if ind.get("ema_strong_bull"):
        score += 2
        reasons.append("EMA 9>21>50")
    elif ind.get("ema_bull"):
        score += 1
        reasons.append("EMA 9>21")

    if ind.get("ema_cross_bull"):
        score += 2
        reasons.append("EMA cross UP")

    if ind.get("above_ema200"):
        score += 1
        reasons.append("Above EMA200")

    # ─── MACD (weight: 2) ──────────────────────────────
    if ind.get("macd_cross_bull"):
        score += 2
        reasons.append("MACD cross UP")
    elif ind.get("macd_bull") and ind.get("macd_hist", 0) > 0:
        score += 1
        reasons.append("MACD bullish")

    # ─── RSI (weight: 2) ───────────────────────────────
    rsi = ind.get("rsi", 50)
    if rsi < 35:
        score += 2
        reasons.append(f"RSI oversold {rsi}")
    elif 35 <= rsi < 50:
        score += 1
        reasons.append(f"RSI recovering {rsi}")
    elif rsi > 70:
        score -= 2  # Overbought = don't buy
        reasons.append(f"RSI overbought {rsi} ⚠")

    # ─── SMC (weight: 3) ───────────────────────────────
    if smc.get("bull_ob"):
        score += 3
        reasons.append("Demand order block")

    if smc.get("bull_fvg"):
        score += 2
        reasons.append("Bullish FVG")

    if smc.get("liquidity_bull"):
        score += 3
        reasons.append("Liquidity swept low ↑")

    if smc.get("bias") == "buy":
        score += 1
        reasons.append("SMC bias: BUY")

    if smc.get("structure", {}).get("bos_bull"):
        score += 2
        reasons.append("Break of structure UP")

    # ─── VWAP (weight: 1) ──────────────────────────────
    if ind.get("above_vwap"):
        score += 1
        reasons.append("Above VWAP")

    # ─── VOLUME (weight: 1) ────────────────────────────
    if ind.get("high_volume") and ind.get("ema_bull"):
        score += 1
        reasons.append("High volume bull")

    # ─── SUPPORT (weight: 1) ───────────────────────────
    if ind.get("near_support"):
        score += 1
        reasons.append("Near support")

    # ─── BOLLINGER (weight: 1) ─────────────────────────
    if ind.get("near_bb_lower"):
        score += 1
        reasons.append("Near BB lower")

    # ─── MOMENTUM (weight: 1) ──────────────────────────
    if ind.get("momentum_bull"):
        score += 1
        reasons.append("Positive momentum")

    return score, reasons


def score_sell(ind, smc):
    """Score bearish signals"""
    score = 0
    reasons = []

    if ind.get("trend") == "BEAR":
        score += 3
        reasons.append("Bear trend")

    if not ind.get("ema_bull"):
        score += 1
        reasons.append("EMA bearish")

    if ind.get("ema_cross_bear"):
        score += 2
        reasons.append("EMA cross DOWN")

    if ind.get("macd_cross_bear"):
        score += 2
        reasons.append("MACD cross DOWN")
    elif not ind.get("macd_bull"):
        score += 1
        reasons.append("MACD bearish")

    rsi = ind.get("rsi", 50)
    if rsi > 70:
        score += 2
        reasons.append(f"RSI overbought {rsi}")
    elif rsi < 35:
        score -= 2

    if smc.get("bear_ob"):
        score += 3
        reasons.append("Supply order block")

    if smc.get("bear_fvg"):
        score += 2
        reasons.append("Bearish FVG")

    if smc.get("liquidity_bear"):
        score += 3
        reasons.append("Liquidity swept high ↓")

    if smc.get("bias") == "sell":
        score += 1
        reasons.append("SMC bias: SELL")

    if not ind.get("above_vwap"):
        score += 1
        reasons.append("Below VWAP")

    if ind.get("near_resistance"):
        score += 1
        reasons.append("Near resistance")

    if ind.get("near_bb_upper"):
        score += 1
        reasons.append("Near BB upper")

    return score, reasons


def decide(ind, smc, state):
    """
    Main decision function
    Returns: (action, confidence, mode, reasons, sl_pct, tp_pct)
    """
    if not ind:
        return "HOLD", 0, "NORMAL", ["No indicators"], 0.5, 1.5

    mode = market_mode(ind, smc)
    atr_pct = ind.get("atr_pct", 0.2)

    # ─── AVOID MODES ──────────────────────────────────
    if mode == "AVOID":
        return "HOLD", 0, mode, ["Choppy market — avoiding"], 0, 0

    # ─── ADAPTIVE TP/SL BASED ON ATR ──────────────────
    # Always: TP >= 2x SL (positive expectancy)
    if atr_pct > 0.5:
        sl_pct = min(atr_pct * 1.5, 1.5)
        tp_pct = sl_pct * 2.5
    elif atr_pct > 0.2:
        sl_pct = max(atr_pct * 1.5, 0.3)
        tp_pct = sl_pct * 2.5
    else:
        sl_pct = 0.3
        tp_pct = 0.9

    # Mode adjustments
    if mode == "TREND":
        tp_pct = sl_pct * 3.5  # Let winners run in trend
    elif mode == "SCALP":
        sl_pct = min(sl_pct, 0.3)
        tp_pct = sl_pct * 2.0

    # ─── THRESHOLDS BY MODE ───────────────────────────
    thresholds = {
        "TREND":    6,   # Need strong confluence in trend
        "SCALP":    4,   # Lower bar for quick scalps
        "REVERSAL": 7,   # Higher bar for reversals
        "NORMAL":   5,   # Standard threshold
    }
    threshold = thresholds.get(mode, 5)

    # ─── SCORE BOTH DIRECTIONS ────────────────────────
    buy_score,  buy_reasons  = score_buy(ind, smc)
    sell_score, sell_reasons = score_sell(ind, smc)

    # ─── EXISTING POSITION CHECK ──────────────────────
    positions = state.get("positions", [])
    if len(positions) >= 2:
        return "HOLD", 0, mode, ["Max positions reached"], sl_pct, tp_pct

    # ─── DAILY LIMITS ─────────────────────────────────
    if state.get("daily_trades", 0) >= 30:
        return "HOLD", 0, mode, ["Daily trade limit reached"], sl_pct, tp_pct

    if state.get("daily_loss", 0) > state.get("balance", 1000) * 0.08:
        return "HOLD", 0, mode, ["Daily loss limit reached"], sl_pct, tp_pct

    # ─── DECISION ─────────────────────────────────────
    if buy_score >= threshold and buy_score > sell_score:
        confidence = min(int((buy_score / (threshold + 4)) * 10), 10)
        return "BUY", confidence, mode, buy_reasons, sl_pct, tp_pct

    if sell_score >= threshold and sell_score > buy_score:
        confidence = min(int((sell_score / (threshold + 4)) * 10), 10)
        return "SELL", confidence, mode, sell_reasons, sl_pct, tp_pct

    return "HOLD", 0, mode, [f"No clear signal (B:{buy_score} S:{sell_score} need {threshold})"], sl_pct, tp_pct
