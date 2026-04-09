"""
Real indicator calculations
RSI, EMA, MACD, Bollinger Bands, ATR, VWAP, Volume
All calculated from real Kraken candle data
"""


def ema(values, period):
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def compute(candles):
    """
    Compute all indicators from candle list
    Returns dict of indicator values
    """
    if not candles or len(candles) < 30:
        return {}

    closes  = [c["close"]  for c in candles]
    highs   = [c["high"]   for c in candles]
    lows    = [c["low"]    for c in candles]
    volumes = [c["volume"] for c in candles]

    ind = {}
    ind["price"] = closes[-1]

    # ─── RSI (14) ─────────────────────────────────────────
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))

    period = 14
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    ind["rsi"] = round(100 - (100 / (1 + ag / al)), 2) if al > 0 else 100

    # RSI signal
    if ind["rsi"] < 30:
        ind["rsi_signal"] = "oversold"
    elif ind["rsi"] > 70:
        ind["rsi_signal"] = "overbought"
    else:
        ind["rsi_signal"] = "neutral"

    # ─── EMA ──────────────────────────────────────────────
    e9  = ema(closes, 9)
    e21 = ema(closes, 21)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200) if len(closes) >= 200 else []

    ind["ema9"]  = round(e9[-1],  2) if e9  else closes[-1]
    ind["ema21"] = round(e21[-1], 2) if e21 else closes[-1]
    ind["ema50"] = round(e50[-1], 2) if e50 else closes[-1]
    ind["ema200"]= round(e200[-1],2) if e200 else closes[-1]

    ind["ema_bull"]         = ind["ema9"] > ind["ema21"]
    ind["ema_strong_bull"]  = ind["ema9"] > ind["ema21"] > ind["ema50"]
    ind["above_ema200"]     = closes[-1] > ind["ema200"]

    # EMA cross detection
    if len(e9) >= 2 and len(e21) >= 2:
        ind["ema_cross_bull"] = e9[-1] > e21[-1] and e9[-2] <= e21[-2]
        ind["ema_cross_bear"] = e9[-1] < e21[-1] and e9[-2] >= e21[-2]
    else:
        ind["ema_cross_bull"] = ind["ema_cross_bear"] = False

    # ─── MACD ─────────────────────────────────────────────
    e12 = ema(closes, 12)
    e26 = ema(closes, 26)
    if e12 and e26:
        diff = len(e12) - len(e26)
        macd_line = [e12[i + diff] - e26[i] for i in range(len(e26))]
        signal_line = ema(macd_line, 9)
        if signal_line:
            ind["macd"]        = round(macd_line[-1], 4)
            ind["macd_signal"] = round(signal_line[-1], 4)
            ind["macd_hist"]   = round(macd_line[-1] - signal_line[-1], 4)
            ind["macd_bull"]   = ind["macd_hist"] > 0
            # Fresh cross
            if len(macd_line) >= 2 and len(signal_line) >= 2:
                ind["macd_cross_bull"] = (macd_line[-1] > signal_line[-1] and
                                          macd_line[-2] <= signal_line[-2])
                ind["macd_cross_bear"] = (macd_line[-1] < signal_line[-1] and
                                          macd_line[-2] >= signal_line[-2])
            else:
                ind["macd_cross_bull"] = ind["macd_cross_bear"] = False
        else:
            ind["macd"] = ind["macd_signal"] = ind["macd_hist"] = 0
            ind["macd_bull"] = ind["macd_cross_bull"] = ind["macd_cross_bear"] = False
    else:
        ind["macd"] = ind["macd_signal"] = ind["macd_hist"] = 0
        ind["macd_bull"] = ind["macd_cross_bull"] = ind["macd_cross_bear"] = False

    # ─── ATR (14) ─────────────────────────────────────────
    trs = []
    for i in range(1, len(candles)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        trs.append(tr)
    ind["atr"]     = round(sum(trs[-14:]) / 14, 4) if len(trs) >= 14 else 0
    ind["atr_pct"] = round(ind["atr"] / closes[-1] * 100, 3) if closes[-1] else 0

    # Volatility level
    if ind["atr_pct"] > 0.5:
        ind["volatility"] = "high"
    elif ind["atr_pct"] > 0.2:
        ind["volatility"] = "medium"
    else:
        ind["volatility"] = "low"

    # ─── BOLLINGER BANDS ──────────────────────────────────
    bb_period = 20
    if len(closes) >= bb_period:
        bb_closes = closes[-bb_period:]
        bb_mid = sum(bb_closes) / bb_period
        bb_std = (sum((c - bb_mid) ** 2 for c in bb_closes) / bb_period) ** 0.5
        ind["bb_upper"] = round(bb_mid + 2 * bb_std, 2)
        ind["bb_lower"] = round(bb_mid - 2 * bb_std, 2)
        ind["bb_mid"]   = round(bb_mid, 2)
        bb_range = ind["bb_upper"] - ind["bb_lower"]
        ind["bb_pct"]   = round((closes[-1] - ind["bb_lower"]) / bb_range, 3) if bb_range > 0 else 0.5
        ind["bb_squeeze"] = bb_range / bb_mid < 0.02
        ind["near_bb_upper"] = closes[-1] > ind["bb_upper"] * 0.998
        ind["near_bb_lower"] = closes[-1] < ind["bb_lower"] * 1.002
    else:
        ind["bb_upper"] = ind["bb_lower"] = ind["bb_mid"] = closes[-1]
        ind["bb_pct"] = 0.5
        ind["bb_squeeze"] = ind["near_bb_upper"] = ind["near_bb_lower"] = False

    # ─── VWAP ─────────────────────────────────────────────
    typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(len(candles))]
    vol_sum = sum(volumes)
    ind["vwap"] = round(
        sum(t * v for t, v in zip(typical, volumes)) / vol_sum, 2
    ) if vol_sum > 0 else closes[-1]
    ind["above_vwap"] = closes[-1] > ind["vwap"]

    # ─── VOLUME ───────────────────────────────────────────
    avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / len(volumes)
    ind["vol_ratio"]   = round(volumes[-1] / avg_vol, 2) if avg_vol > 0 else 1
    ind["high_volume"] = ind["vol_ratio"] > 1.5

    # ─── SUPPORT & RESISTANCE ─────────────────────────────
    ind["support"]    = round(min(lows[-20:]),  2)
    ind["resistance"] = round(max(highs[-20:]), 2)
    ind["near_support"]    = abs(closes[-1] - ind["support"])    / closes[-1] < 0.003
    ind["near_resistance"] = abs(closes[-1] - ind["resistance"]) / closes[-1] < 0.003

    # ─── TREND ────────────────────────────────────────────
    if len(closes) >= 6:
        ind["higher_highs"] = max(highs[-3:]) > max(highs[-6:-3])
        ind["higher_lows"]  = min(lows[-3:])  > min(lows[-6:-3])
        ind["lower_lows"]   = min(lows[-3:])  < min(lows[-6:-3])
        ind["lower_highs"]  = max(highs[-3:]) < max(highs[-6:-3])
    else:
        ind["higher_highs"] = ind["higher_lows"] = False
        ind["lower_lows"]   = ind["lower_highs"] = False

    if ind["higher_highs"] and ind["higher_lows"] and ind["ema_strong_bull"]:
        ind["trend"] = "STRONG_BULL"
    elif ind["higher_highs"] and ind["higher_lows"]:
        ind["trend"] = "BULL"
    elif ind["lower_lows"] and ind["lower_highs"]:
        ind["trend"] = "BEAR"
    else:
        ind["trend"] = "RANGING"

    # ─── MOMENTUM ─────────────────────────────────────────
    if len(closes) >= 5:
        momentum = (closes[-1] - closes[-5]) / closes[-5] * 100
        ind["momentum"] = round(momentum, 3)
        ind["momentum_bull"] = momentum > 0.1
    else:
        ind["momentum"] = 0
        ind["momentum_bull"] = False

    return ind
