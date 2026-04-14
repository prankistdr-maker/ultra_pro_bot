"""
ADVANCED SMC ENGINE - Institutional Level
==========================================
Concepts implemented:
1. CHoCH (Change of Character) - MOST IMPORTANT trend reversal signal
2. BOS (Break of Structure) - trend continuation confirmation  
3. Order Blocks with MITIGATION tracking
4. Fair Value Gaps with INVALIDATION
5. Liquidity Levels (equal highs/lows = stop hunt targets)
6. Premium/Discount zones (Golden Ratio entries)
7. Displacement candles (explosive institutional moves)
8. Multi-timeframe structure alignment

KEY INSIGHT: 
- CHoCH = first sign smart money changed direction
- BOS = confirmation of new trend
- Only enter in DISCOUNT zone for BUY (below 50% of range)
- Only enter in PREMIUM zone for SELL (above 50% of range)
- Wait for price to return to OB/FVG AFTER CHoCH/BOS
"""


def find_swing_points(candles, lookback=5):
    """
    Find significant swing highs and lows.
    A swing high = highest point with lower highs on both sides
    A swing low = lowest point with higher lows on both sides
    These are the KEY levels smart money targets
    """
    highs = [c["high"] for c in candles]
    lows  = [c["low"]  for c in candles]
    swing_highs = []
    swing_lows  = []

    for i in range(lookback, len(candles) - lookback):
        # Swing high: highest in window
        if highs[i] == max(highs[i-lookback:i+lookback+1]):
            swing_highs.append({"idx": i, "price": highs[i], "time": candles[i]["time"]})
        # Swing low: lowest in window  
        if lows[i] == min(lows[i-lookback:i+lookback+1]):
            swing_lows.append({"idx": i, "price": lows[i], "time": candles[i]["time"]})

    return swing_highs[-6:], swing_lows[-6:]  # Last 6 of each


def detect_choch_bos(candles):
    """
    CHoCH = Change of Character
    - In downtrend: first time price breaks above a RECENT swing high = CHoCH (bullish)
    - In uptrend: first time price breaks below a RECENT swing low = CHoCH (bearish)
    
    BOS = Break of Structure  
    - In uptrend: price breaks above previous swing high = BOS (continuation)
    - In downtrend: price breaks below previous swing low = BOS (continuation)
    
    CHoCH is MORE POWERFUL than BOS - it signals smart money reversal
    """
    if len(candles) < 20:
        return {
            "choch_bull": False, "choch_bear": False,
            "bos_bull": False, "bos_bear": False,
            "structure": "neutral", "strength": 0
        }

    closes = [c["close"] for c in candles]
    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]

    swing_highs, swing_lows = find_swing_points(candles, lookback=3)

    choch_bull = False
    choch_bear = False
    bos_bull   = False
    bos_bear   = False

    current_close = closes[-1]
    prev_close    = closes[-2]

    # Determine current structure (last 15 candles)
    recent_highs = highs[-15:]
    recent_lows  = lows[-15:]

    # Simple structure: are we making HH/HL or LH/LL?
    mid = len(recent_highs) // 2
    first_half_high = max(recent_highs[:mid])
    second_half_high = max(recent_highs[mid:])
    first_half_low  = min(recent_lows[:mid])
    second_half_low  = min(recent_lows[mid:])

    in_uptrend   = second_half_high > first_half_high and second_half_low > first_half_low
    in_downtrend = second_half_high < first_half_high and second_half_low < first_half_low

    # CHoCH BULL: Was in downtrend, now breaks above recent swing high
    if in_downtrend and swing_highs:
        last_sh = swing_highs[-1]["price"]
        if current_close > last_sh and prev_close <= last_sh:
            choch_bull = True

    # CHoCH BEAR: Was in uptrend, now breaks below recent swing low
    if in_uptrend and swing_lows:
        last_sl = swing_lows[-1]["price"]
        if current_close < last_sl and prev_close >= last_sl:
            choch_bear = True

    # BOS BULL: In uptrend, breaks above previous swing high (continuation)
    if in_uptrend and swing_highs and len(swing_highs) >= 2:
        prev_sh = swing_highs[-2]["price"]
        if current_close > prev_sh and not choch_bull:
            bos_bull = True

    # BOS BEAR: In downtrend, breaks below previous swing low (continuation)
    if in_downtrend and swing_lows and len(swing_lows) >= 2:
        prev_sl = swing_lows[-2]["price"]
        if current_close < prev_sl and not choch_bear:
            bos_bear = True

    # Structure
    if choch_bull or bos_bull: structure = "bullish"
    elif choch_bear or bos_bear: structure = "bearish"
    elif in_uptrend: structure = "uptrend"
    elif in_downtrend: structure = "downtrend"
    else: structure = "ranging"

    strength = 3 if (choch_bull or choch_bear) else (2 if (bos_bull or bos_bear) else 1)

    return {
        "choch_bull": choch_bull,
        "choch_bear": choch_bear,
        "bos_bull":   bos_bull,
        "bos_bear":   bos_bear,
        "structure":  structure,
        "strength":   strength,
        "in_uptrend": in_uptrend,
        "in_downtrend": in_downtrend,
        "swing_highs": [s["price"] for s in swing_highs[-3:]],
        "swing_lows":  [s["price"] for s in swing_lows[-3:]],
    }


def find_order_blocks(candles):
    """
    INSTITUTIONAL Order Blocks:
    
    Bullish OB = Last BEARISH candle before a strong BULLISH impulse
    - Price returns to this zone = institutional buy orders waiting
    - Valid until MITIGATED (price closes below the OB low)
    
    Bearish OB = Last BULLISH candle before a strong BEARISH impulse  
    - Price returns to this zone = institutional sell orders waiting
    - Valid until MITIGATED (price closes above the OB high)
    
    STRONG OB characteristics:
    - Large body candle (>60% body ratio)
    - Followed by 2+ candles going opposite direction
    - Volume spike on the OB candle
    """
    if len(candles) < 10:
        return {
            "bull_ob": False, "bear_ob": False,
            "bull_ob_high": 0, "bull_ob_low": 0,
            "bear_ob_high": 0, "bear_ob_low": 0,
            "ob_strength": 0
        }

    closes  = [c["close"]  for c in candles]
    opens   = [c["open"]   for c in candles]
    highs   = [c["high"]   for c in candles]
    lows    = [c["low"]    for c in candles]
    volumes = [c["volume"] for c in candles]
    price   = closes[-1]
    avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1

    bull_ob = False; bear_ob = False
    bull_ob_high = 0; bull_ob_low = 0
    bear_ob_high = 0; bear_ob_low = 0
    ob_strength  = 0

    # Search last 15 candles for OB formations
    for i in range(max(1, len(candles)-15), len(candles)-2):
        candle_range = highs[i] - lows[i]
        if candle_range == 0:
            continue
        body = abs(closes[i] - opens[i])
        body_ratio = body / candle_range

        is_bearish = closes[i] < opens[i]
        is_bullish = closes[i] > opens[i]
        high_vol   = volumes[i] > avg_vol * 1.2

        # BULLISH OB: bearish candle followed by strong bullish impulse
        if is_bearish and body_ratio > 0.5:
            # Check if followed by bullish impulse (closes above OB high)
            if i+2 < len(candles):
                impulse = max(closes[i+1:i+3])
                if impulse > highs[i]:  # Strong bullish impulse
                    ob_high = max(opens[i], closes[i])  # OB zone
                    ob_low  = min(opens[i], closes[i])
                    # Is current price IN the OB zone?
                    if ob_low <= price <= ob_high * 1.003:
                        # Not mitigated (price hasn't closed below OB low)
                        if min(closes[i+1:]) > ob_low * 0.998:
                            bull_ob      = True
                            bull_ob_high = ob_high
                            bull_ob_low  = ob_low
                            ob_strength  = 3 if high_vol else 2

        # BEARISH OB: bullish candle followed by strong bearish impulse
        if is_bullish and body_ratio > 0.5:
            if i+2 < len(candles):
                impulse = min(closes[i+1:i+3])
                if impulse < lows[i]:  # Strong bearish impulse
                    ob_high = max(opens[i], closes[i])
                    ob_low  = min(opens[i], closes[i])
                    if ob_low * 0.997 <= price <= ob_high:
                        if max(closes[i+1:]) < ob_high * 1.002:
                            bear_ob      = True
                            bear_ob_high = ob_high
                            bear_ob_low  = ob_low
                            ob_strength  = 3 if high_vol else 2

    return {
        "bull_ob":      bull_ob,
        "bear_ob":      bear_ob,
        "bull_ob_high": bull_ob_high,
        "bull_ob_low":  bull_ob_low,
        "bear_ob_high": bear_ob_high,
        "bear_ob_low":  bear_ob_low,
        "ob_strength":  ob_strength,
    }


def find_fvg(candles):
    """
    Fair Value Gap (FVG) / Imbalance
    
    Bullish FVG: candle[i].high < candle[i+2].low
    = Gap between two candles — price "should" fill it
    = 70%+ probability price returns to fill
    
    Bearish FVG: candle[i].low > candle[i+2].high
    
    FVG becomes TP TARGET when price is away from it
    FVG becomes ENTRY when price returns to test it
    """
    if len(candles) < 5:
        return {
            "bull_fvg": False, "bear_fvg": False,
            "bull_fvg_high": 0, "bull_fvg_low": 0,
            "bear_fvg_high": 0, "bear_fvg_low": 0,
            "fvg_size_pct": 0
        }

    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    closes = [c["close"] for c in candles]
    price  = closes[-1]

    bull_fvg = False; bear_fvg = False
    bull_fvg_high = 0; bull_fvg_low = 0
    bear_fvg_high = 0; bear_fvg_low = 0
    fvg_size_pct  = 0

    # Check last 8 candles for FVGs
    for i in range(max(0, len(candles)-8), len(candles)-2):
        # Bullish FVG
        gap_low  = highs[i]
        gap_high = lows[i+2]
        if gap_high > gap_low:  # Gap exists
            size_pct = (gap_high - gap_low) / gap_low * 100
            if size_pct > 0.05:  # Meaningful gap (>0.05%)
                # Is price in or near this FVG?
                if gap_low <= price <= gap_high * 1.002:
                    bull_fvg      = True
                    bull_fvg_high = gap_high
                    bull_fvg_low  = gap_low
                    fvg_size_pct  = round(size_pct, 3)
                    break

        # Bearish FVG
        gap_high2 = lows[i]
        gap_low2  = highs[i+2]
        if gap_high2 > gap_low2:
            size_pct = (gap_high2 - gap_low2) / gap_low2 * 100
            if size_pct > 0.05:
                if gap_low2 * 0.998 <= price <= gap_high2:
                    bear_fvg      = True
                    bear_fvg_high = gap_high2
                    bear_fvg_low  = gap_low2
                    fvg_size_pct  = round(size_pct, 3)
                    break

    return {
        "bull_fvg":      bull_fvg,
        "bear_fvg":      bear_fvg,
        "bull_fvg_high": bull_fvg_high,
        "bull_fvg_low":  bull_fvg_low,
        "bear_fvg_high": bear_fvg_high,
        "bear_fvg_low":  bear_fvg_low,
        "fvg_size_pct":  fvg_size_pct,
    }


def find_liquidity_levels(candles):
    """
    Liquidity = where retail stop losses cluster
    = Equal highs / equal lows (magnets for smart money)
    
    Smart money HUNTS liquidity before real move:
    - Equal highs above = sell-side liquidity (smart money will push above, then reverse)
    - Equal lows below  = buy-side liquidity (smart money will push below, then reverse)
    
    After liquidity sweep → expect REVERSAL
    """
    if len(candles) < 20:
        return {
            "equal_highs": [], "equal_lows": [],
            "liq_sweep_bull": False, "liq_sweep_bear": False,
            "sweep_strength": 0
        }

    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    closes = [c["close"] for c in candles]
    price  = closes[-1]

    # Find equal highs (within 0.1% of each other)
    equal_highs = []
    for i in range(len(highs)-15, len(highs)-1):
        for j in range(i+1, len(highs)):
            if abs(highs[i] - highs[j]) / highs[i] < 0.001:
                equal_highs.append(highs[i])
                break

    # Find equal lows
    equal_lows = []
    for i in range(len(lows)-15, len(lows)-1):
        for j in range(i+1, len(lows)):
            if abs(lows[i] - lows[j]) / lows[i] < 0.001:
                equal_lows.append(lows[i])
                break

    # Liquidity sweep detection
    prev_high = max(highs[-25:-3]) if len(highs) >= 25 else max(highs[:-3])
    prev_low  = min(lows[-25:-3])  if len(lows)  >= 25 else min(lows[:-3])

    # BULL sweep: went below prev_low then recovered (grabbed buy-side liq)
    liq_sweep_bull = (
        min(lows[-4:]) < prev_low and
        closes[-1] > prev_low and
        closes[-1] > closes[-2]  # Closing bullish after sweep
    )

    # BEAR sweep: went above prev_high then reversed (grabbed sell-side liq)
    liq_sweep_bear = (
        max(highs[-4:]) > prev_high and
        closes[-1] < prev_high and
        closes[-1] < closes[-2]  # Closing bearish after sweep
    )

    # Sweep strength based on how far it swept
    sweep_strength = 0
    if liq_sweep_bull:
        pips_swept = (prev_low - min(lows[-4:])) / prev_low * 100
        sweep_strength = min(int(pips_swept * 10), 5)
    elif liq_sweep_bear:
        pips_swept = (max(highs[-4:]) - prev_high) / prev_high * 100
        sweep_strength = min(int(pips_swept * 10), 5)

    return {
        "equal_highs":     equal_highs[-3:],
        "equal_lows":      equal_lows[-3:],
        "liq_sweep_bull":  liq_sweep_bull,
        "liq_sweep_bear":  liq_sweep_bear,
        "sweep_strength":  sweep_strength,
        "prev_high":       prev_high,
        "prev_low":        prev_low,
    }


def find_displacement(candles):
    """
    Displacement = explosive candle showing institutional interest
    - Body > 3x average body size
    - Often creates FVG
    - Signals start of real move (not retail noise)
    
    After displacement: wait for pullback to OB/FVG → entry
    """
    if len(candles) < 10:
        return {"bull_disp": False, "bear_disp": False, "disp_strength": 0}

    closes = [c["close"] for c in candles]
    opens  = [c["open"]  for c in candles]
    vols   = [c["volume"] for c in candles]

    bodies   = [abs(closes[i] - opens[i]) for i in range(len(candles))]
    avg_body = sum(bodies[-20:]) / 20 if len(bodies) >= 20 else sum(bodies) / len(bodies)
    avg_vol  = sum(vols[-20:]) / 20

    curr_body = bodies[-2]  # Previous candle (completed)
    curr_vol  = vols[-2]

    disp_threshold = avg_body * 2.5

    bull_disp = (
        curr_body > disp_threshold and
        closes[-2] > opens[-2] and     # Bullish candle
        curr_vol > avg_vol * 1.5       # High volume
    )
    bear_disp = (
        curr_body > disp_threshold and
        closes[-2] < opens[-2] and     # Bearish candle
        curr_vol > avg_vol * 1.5
    )

    disp_strength = round(curr_body / avg_body, 1) if avg_body > 0 else 0

    return {
        "bull_disp":    bull_disp,
        "bear_disp":    bear_disp,
        "disp_strength": disp_strength,
    }


def premium_discount_zone(candles, swing_high=None, swing_low=None):
    """
    Premium/Discount Zone (Golden Ratio concept)
    
    Range = swing_high to swing_low
    - Below 50% = DISCOUNT zone → only BUY here
    - Above 50% = PREMIUM zone → only SELL here
    - 50% = equilibrium (avoid)
    
    Best entries:
    - BUY in discount (below 50%) at OB/FVG
    - SELL in premium (above 50%) at OB/FVG
    
    This filters out entries at wrong prices
    """
    if len(candles) < 20:
        return {"zone": "equilibrium", "zone_pct": 0.5, "discount": False, "premium": False}

    highs  = [c["high"]  for c in candles]
    lows   = [c["low"]   for c in candles]
    price  = candles[-1]["close"]

    sh = swing_high or max(highs[-30:])
    sl = swing_low  or min(lows[-30:])

    if sh == sl:
        return {"zone": "equilibrium", "zone_pct": 0.5, "discount": False, "premium": False}

    zone_pct = (price - sl) / (sh - sl)

    if zone_pct < 0.45:
        zone = "discount"
    elif zone_pct > 0.55:
        zone = "premium"
    else:
        zone = "equilibrium"

    return {
        "zone":      zone,
        "zone_pct":  round(zone_pct, 3),
        "discount":  zone == "discount",
        "premium":   zone == "premium",
        "range_high": sh,
        "range_low":  sl,
    }


def full_smc_analysis(candles_5m, candles_1h=None):
    """
    Complete SMC analysis combining all concepts.
    
    Multi-timeframe:
    - 1H = structure (macro bias)
    - 5M = entry timing (micro execution)
    
    Only take 5M trades aligned with 1H structure.
    This eliminates counter-trend trades that keep losing.
    """
    if not candles_5m or len(candles_5m) < 30:
        return {}

    # Core analysis on 5m
    structure  = detect_choch_bos(candles_5m)
    ob         = find_order_blocks(candles_5m)
    fvg        = find_fvg(candles_5m)
    liquidity  = find_liquidity_levels(candles_5m)
    disp       = find_displacement(candles_5m)
    pd_zone    = premium_discount_zone(candles_5m)

    # 1H bias if available
    htf_bias = "neutral"
    if candles_1h and len(candles_1h) >= 20:
        htf_struct = detect_choch_bos(candles_1h)
        if htf_struct["structure"] in ["bullish", "uptrend"]:
            htf_bias = "buy"
        elif htf_struct["structure"] in ["bearish", "downtrend"]:
            htf_bias = "sell"

    # Overall bias from structure
    if structure["choch_bull"] or structure["bos_bull"]:
        bias = "buy"
    elif structure["choch_bear"] or structure["bos_bear"]:
        bias = "sell"
    elif structure["in_uptrend"]:
        bias = "buy"
    elif structure["in_downtrend"]:
        bias = "sell"
    else:
        bias = "neutral"

    # Key entry signals
    high_prob_buy = (
        (structure["choch_bull"] or liquidity["liq_sweep_bull"]) and
        (ob["bull_ob"] or fvg["bull_fvg"]) and
        pd_zone["discount"]  # Price in discount zone
    )

    high_prob_sell = (
        (structure["choch_bear"] or liquidity["liq_sweep_bear"]) and
        (ob["bear_ob"] or fvg["bear_fvg"]) and
        pd_zone["premium"]  # Price in premium zone
    )

    return {
        # Structure
        "choch_bull":    structure["choch_bull"],
        "choch_bear":    structure["choch_bear"],
        "bos_bull":      structure["bos_bull"],
        "bos_bear":      structure["bos_bear"],
        "mkt_structure": structure["structure"],
        "swing_highs":   structure["swing_highs"],
        "swing_lows":    structure["swing_lows"],

        # Order Blocks
        "bull_ob":       ob["bull_ob"],
        "bear_ob":       ob["bear_ob"],
        "bull_ob_high":  ob["bull_ob_high"],
        "bull_ob_low":   ob["bull_ob_low"],
        "bear_ob_high":  ob["bear_ob_high"],
        "bear_ob_low":   ob["bear_ob_low"],
        "ob_strength":   ob["ob_strength"],

        # FVG
        "bull_fvg":      fvg["bull_fvg"],
        "bear_fvg":      fvg["bear_fvg"],
        "bull_fvg_high": fvg["bull_fvg_high"],
        "bull_fvg_low":  fvg["bull_fvg_low"],
        "bear_fvg_high": fvg["bear_fvg_high"],
        "bear_fvg_low":  fvg["bear_fvg_low"],

        # Liquidity
        "liquidity_bull":  liquidity["liq_sweep_bull"],
        "liquidity_bear":  liquidity["liq_sweep_bear"],
        "sweep_strength":  liquidity["sweep_strength"],
        "equal_highs":     liquidity["equal_highs"],
        "equal_lows":      liquidity["equal_lows"],

        # Displacement
        "bull_disp":     disp["bull_disp"],
        "bear_disp":     disp["bear_disp"],
        "disp_strength": disp["disp_strength"],

        # Zone
        "pd_zone":       pd_zone["zone"],
        "zone_pct":      pd_zone["zone_pct"],
        "discount":      pd_zone["discount"],
        "premium":       pd_zone["premium"],

        # Summary
        "bias":          bias,
        "htf_bias":      htf_bias,
        "high_prob_buy":  high_prob_buy,
        "high_prob_sell": high_prob_sell,
    }
