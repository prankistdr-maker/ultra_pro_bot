"""
Smart Money Concepts (SMC) Analysis
- Market Structure (BOS, ChoCH)
- Order Blocks
- Fair Value Gaps (FVG)
- Liquidity Sweeps
- Imbalances
"""


def market_structure(candles):
    """
    Detect market structure:
    - BOS (Break of Structure) = trend continuation
    - ChoCH (Change of Character) = trend reversal
    - HH/HL = bullish structure
    - LH/LL = bearish structure
    """
    if len(candles) < 10:
        return {"type": "neutral", "bias": "neutral"}

    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    closes = [c["close"] for c in candles]

    # Last 3 swing points
    recent_highs = highs[-10:]
    recent_lows  = lows[-10:]

    prev_high = max(recent_highs[:-3])
    prev_low  = min(recent_lows[:-3])
    curr_high = max(recent_highs[-3:])
    curr_low  = min(recent_lows[-3:])

    hh = curr_high > prev_high  # Higher High
    hl = curr_low  > prev_low   # Higher Low
    lh = curr_high < prev_high  # Lower High
    ll = curr_low  < prev_low   # Lower Low

    # BOS detection
    bos_bull = closes[-1] > max(highs[-20:-5]) if len(candles) >= 20 else False
    bos_bear = closes[-1] < min(lows[-20:-5])  if len(candles) >= 20 else False

    if hh and hl:
        structure = "bullish"
        bias = "buy"
    elif lh and ll:
        structure = "bearish"
        bias = "sell"
    elif hh and ll:
        structure = "ranging"
        bias = "neutral"
    else:
        structure = "neutral"
        bias = "neutral"

    return {
        "type":     structure,
        "bias":     bias,
        "hh":       hh,
        "hl":       hl,
        "lh":       lh,
        "ll":       ll,
        "bos_bull": bos_bull,
        "bos_bear": bos_bear
    }


def find_order_blocks(candles):
    """
    Order Block: Last bearish candle before a strong bullish move (demand OB)
    or last bullish candle before a strong bearish move (supply OB)
    Price returns to OB = high probability entry
    """
    if len(candles) < 10:
        return {"bull_ob": False, "bear_ob": False, "ob_zone": None}

    closes = [c["close"] for c in candles]
    opens  = [c["open"]  for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    price  = closes[-1]

    # Bullish OB: bearish candle followed by 2+ bullish candles
    # Price retracing back into the bearish candle = entry
    bull_ob = False
    ob_zone = None

    for i in range(len(candles)-4, len(candles)-1):
        if i < 1:
            continue
        # Bearish candle at i
        if closes[i] < opens[i]:
            # Followed by bullish impulse
            if (closes[i+1] > opens[i+1] and
                    closes[i+1] > highs[i]):
                ob_high = opens[i]
                ob_low  = closes[i]
                # Price returning to OB zone
                if ob_low <= price <= ob_high * 1.002:
                    bull_ob = True
                    ob_zone = {"high": ob_high, "low": ob_low, "type": "demand"}
                    break

    # Bearish OB: bullish candle followed by bearish impulse
    bear_ob = False
    for i in range(len(candles)-4, len(candles)-1):
        if i < 1:
            continue
        if closes[i] > opens[i]:
            if (closes[i+1] < opens[i+1] and
                    closes[i+1] < lows[i]):
                ob_high = closes[i]
                ob_low  = opens[i]
                if ob_low * 0.998 <= price <= ob_high:
                    bear_ob = True
                    ob_zone = {"high": ob_high, "low": ob_low, "type": "supply"}
                    break

    return {
        "bull_ob": bull_ob,
        "bear_ob": bear_ob,
        "ob_zone": ob_zone
    }


def find_fvg(candles):
    """
    Fair Value Gap (FVG): 3-candle pattern where candle 1 high < candle 3 low (bullish)
    or candle 1 low > candle 3 high (bearish)
    Price always returns to fill the gap ~70% of time
    """
    if len(candles) < 5:
        return {"bull_fvg": False, "bear_fvg": False, "fvg_zone": None}

    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    price  = candles[-1]["close"]

    bull_fvg = False
    bear_fvg = False
    fvg_zone = None

    # Check last 5 candles for FVG
    for i in range(len(candles)-5, len(candles)-2):
        if i < 0:
            continue
        # Bullish FVG: gap between candle[i] high and candle[i+2] low
        if lows[i+2] > highs[i]:
            gap_low  = highs[i]
            gap_high = lows[i+2]
            # Price near the gap = fill incoming
            if gap_low <= price <= gap_high * 1.003:
                bull_fvg = True
                fvg_zone = {"high": gap_high, "low": gap_low, "type": "bullish"}
                break

        # Bearish FVG: gap between candle[i] low and candle[i+2] high
        if highs[i+2] < lows[i]:
            gap_high = lows[i]
            gap_low  = highs[i+2]
            if gap_low * 0.997 <= price <= gap_high:
                bear_fvg = True
                fvg_zone = {"high": gap_high, "low": gap_low, "type": "bearish"}
                break

    return {
        "bull_fvg": bull_fvg,
        "bear_fvg": bear_fvg,
        "fvg_zone": fvg_zone
    }


def liquidity_sweep(candles):
    """
    Liquidity sweep: price briefly breaks above previous highs/lows
    then reverses — trap retail traders before real move
    Strong reversal signal
    """
    if len(candles) < 25:
        return {"swept_high": False, "swept_low": False, "sweep_strength": 0}

    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    closes = [c["close"] for c in candles]

    # Previous structure high/low (20 candles back)
    prev_high = max(highs[-25:-5])
    prev_low  = min(lows[-25:-5])

    # Current price action
    curr_high = max(highs[-5:])
    curr_low  = min(lows[-5:])
    curr_close = closes[-1]

    # Bullish sweep: price swept below prev low then reversed up
    swept_low = (curr_low < prev_low and curr_close > prev_low)

    # Bearish sweep: price swept above prev high then reversed down
    swept_high = (curr_high > prev_high and curr_close < prev_high)

    strength = 0
    if swept_low:
        strength = round((curr_close - curr_low) / curr_low * 100, 3)
    elif swept_high:
        strength = round((curr_high - curr_close) / curr_high * 100, 3)

    return {
        "swept_high":     swept_high,
        "swept_low":      swept_low,
        "sweep_strength": strength
    }


def analyze_smc(candles):
    """Run all SMC analysis and return combined result"""
    if not candles or len(candles) < 20:
        return {}

    ms  = market_structure(candles)
    ob  = find_order_blocks(candles)
    fvg = find_fvg(candles)
    liq = liquidity_sweep(candles)

    return {
        "structure": ms,
        "order_block": ob,
        "fvg": fvg,
        "liquidity": liq,

        # Quick access
        "bias":          ms["bias"],
        "bull_ob":       ob["bull_ob"],
        "bear_ob":       ob["bear_ob"],
        "bull_fvg":      fvg["bull_fvg"],
        "bear_fvg":      fvg["bear_fvg"],
        "liquidity_bull":liq["swept_low"],
        "liquidity_bear":liq["swept_high"],
    }
