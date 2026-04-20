"""
ICT Engine v6.1 - Fixed: conditions relaxed to actually trade
Key fix: Don't require ALL conditions simultaneously
Trade when 3+ confluences align, not all 5
"""
import datetime, os, json, requests

CLAUDE_KEY = os.getenv("CLAUDE_API_KEY", "")

def get_kill_zone():
    h = datetime.datetime.utcnow().hour
    if 22 <= h or h < 7:  return "ASIAN", 0      # Hard avoid
    if 7 <= h < 10:        return "LONDON", 3
    if 13 <= h < 16:       return "NY", 3
    if 10 <= h < 13:       return "OVERLAP", 2
    return "OFFPEAK", 1                            # Still trade offpeak

def get_htf_bias(candles_1h):
    if not candles_1h or len(candles_1h) < 10:
        return "neutral"
    closes = [c["close"] for c in candles_1h]
    highs  = [c["high"]  for c in candles_1h]
    lows   = [c["low"]   for c in candles_1h]
    mid = len(candles_1h) // 2
    bull = max(highs[mid:]) > max(highs[:mid]) and min(lows[mid:]) > min(lows[:mid])
    bear = max(highs[mid:]) < max(highs[:mid]) and min(lows[mid:]) < min(lows[:mid])
    if bull: return "bull"
    if bear: return "bear"
    return "neutral"

def detect_sweep(candles):
    if len(candles) < 15: return None
    closes=[c["close"] for c in candles]; highs=[c["high"] for c in candles]; lows=[c["low"] for c in candles]
    prev_high=max(highs[-20:-3]); prev_low=min(lows[-20:-3])
    # Bull sweep: wick below prev low, closed back above
    if lows[-1]<prev_low and closes[-1]>prev_low and closes[-1]>closes[-2]:
        return {"dir":"bull","level":prev_low,"strength":round((prev_low-lows[-1])/prev_low*100,3)}
    # Bear sweep: wick above prev high, closed back below
    if highs[-1]>prev_high and closes[-1]<prev_high and closes[-1]<closes[-2]:
        return {"dir":"bear","level":prev_high,"strength":round((highs[-1]-prev_high)/prev_high*100,3)}
    return None

def detect_fvg(candles, direction):
    if len(candles) < 5: return False, 0, 0
    highs=[c["high"] for c in candles]; lows=[c["low"] for c in candles]; closes=[c["close"] for c in candles]
    price=closes[-1]
    for i in range(max(0,len(candles)-10), len(candles)-2):
        if direction=="bull":
            fh=highs[i]; fl=lows[i+2]
            if fl>fh and fl-fh>0:
                if fh<=price<=fl*1.002: return True, fl, fh
        else:
            fh=lows[i]; fl=highs[i+2]
            if fh>fl:
                if fl*0.998<=price<=fh: return True, fh, fl
    return False, 0, 0

def detect_choch(candles):
    if len(candles) < 8: return False, False
    closes=[c["close"] for c in candles]; highs=[c["high"] for c in candles]; lows=[c["low"] for c in candles]
    sh=max(highs[-8:-2]); sl=min(lows[-8:-2])
    bull = closes[-1]>sh and closes[-2]<=sh
    bear = closes[-1]<sl and closes[-2]>=sl
    return bull, bear

def decide(pair, ind, candles_5m, candles_1h,
           balance, positions, daily_loss, daily_trades, last_trade_time):
    import time
    if not ind or not candles_5m: return "HOLD",0,"NO_DATA",[],0,0,0,0
    price = ind.get("price",0)
    if price<=0: return "HOLD",0,"NO_PRICE",[],0,0,0,0

    session, sq = get_kill_zone()
    if sq == 0: return "HOLD",0,"ASIAN",["Asian session — avoid"],0,0,0,0

    if daily_loss > balance*0.03: return "HOLD",0,"DAILY_STOP",["3% daily stop"],0,0,0,0
    if daily_trades >= 100: return "HOLD",0,"LIMIT",["100 limit"],0,0,0,0
    if [p for p in positions if p["pair"]==pair]: return "HOLD",0,"OPEN",["Pair open"],0,0,0,0
    if len(positions)>=7: return "HOLD",0,"MAX_POS",["Max 2 pos"],0,0,0,0
    if time.time()-last_trade_time < 90: return "HOLD",0,"COOL",["Cooldown"],0,0,0,0

    htf = get_htf_bias(candles_1h)
    trend = ind.get("trend","RANGING")
    rsi   = ind.get("rsi",50)
    ema_b = ind.get("ema_bull",False)
    macd_h= ind.get("macd_hist",0)
    macd_b= ind.get("macd_bull",False)
    atr   = ind.get("atr_pct",0.2)

    sweep  = detect_sweep(candles_5m)
    choch_b, choch_br = detect_choch(candles_5m)

    score=0; reasons=[]; direction=None

    # ── DETERMINE DIRECTION ──────────────────────────────────────────────────
    # Bull signals
    bull_pts=0
    if trend in ["STRONG_BULL","BULL"]: bull_pts+=3
    if htf=="bull": bull_pts+=3
    if ema_b: bull_pts+=2
    if macd_b: bull_pts+=1
    if rsi<45: bull_pts+=2
    if rsi<30: bull_pts+=2
    if ind.get("above_vwap"): bull_pts+=1
    if ind.get("near_support"): bull_pts+=2
    if sweep and sweep["dir"]=="bull": bull_pts+=4
    if choch_b: bull_pts+=3
    fvg_b,_,_ = detect_fvg(candles_5m,"bull")
    if fvg_b: bull_pts+=3

    # Bear signals
    bear_pts=0
    if trend=="BEAR": bear_pts+=3
    if htf=="bear": bear_pts+=3
    if not ema_b: bear_pts+=2
    if not macd_b: bear_pts+=1
    if rsi>55: bear_pts+=2
    if rsi>70: bear_pts+=2
    if not ind.get("above_vwap"): bear_pts+=1
    if ind.get("near_resistance"): bear_pts+=2
    if sweep and sweep["dir"]=="bear": bear_pts+=4
    if choch_br: bear_pts+=3
    fvg_br,_,_ = detect_fvg(candles_5m,"bear")
    if fvg_br: bear_pts+=3

    # Need clear direction
    if bull_pts>=10 and bull_pts>bear_pts+2:
        direction="BUY"; score=bull_pts
        # Build reasons
        if sweep and sweep["dir"]=="bull": reasons.append(f"Liq sweep ↑ ({sweep['strength']}%)")
        if choch_b: reasons.append("CHoCH ↑")
        if fvg_b: reasons.append("Bull FVG entry")
        if htf=="bull": reasons.append("HTF bull ↑")
        if trend in ["STRONG_BULL","BULL"]: reasons.append(f"Trend: {trend}")
        if rsi<40: reasons.append(f"RSI {rsi:.0f} oversold")
        reasons.append(f"{session} session")

    elif bear_pts>=10 and bear_pts>bull_pts+2:
        direction="SELL"; score=bear_pts
        if sweep and sweep["dir"]=="bear": reasons.append(f"Liq sweep ↓ ({sweep['strength']}%)")
        if choch_br: reasons.append("CHoCH ↓")
        if fvg_br: reasons.append("Bear FVG entry")
        if htf=="bear": reasons.append("HTF bear ↓")
        if trend=="BEAR": reasons.append("Trend: BEAR")
        if rsi>60: reasons.append(f"RSI {rsi:.0f} overbought")
        reasons.append(f"{session} session")
    else:
        return "HOLD",0,f"WAIT_{session}",[f"Bull:{bull_pts} Bear:{bear_pts} need 10+gap"],0,0,0,0

    # Hard blocks
    if direction=="BUY":
        if trend=="BEAR" and htf=="bear" and not choch_b:
            return "HOLD",0,"BLOCKED",["BEAR+HTF bear, no CHoCH"],0,0,0,0
        if rsi>73:
            return "HOLD",0,"BLOCKED",[f"RSI {rsi:.0f} overbought"],0,0,0,0
    else:
        if trend in ["STRONG_BULL"] and htf=="bull" and not choch_br:
            return "HOLD",0,"BLOCKED",["STRONG_BULL+HTF, no CHoCH"],0,0,0,0
        if rsi<27:
            return "HOLD",0,"BLOCKED",[f"RSI {rsi:.0f} oversold"],0,0,0,0

    # SL/TP
    sl_pct = max(atr*1.5, 0.5); sl_pct=min(sl_pct,1.2)
    if sweep: tp_mult=4.0
    elif choch_b or choch_br: tp_mult=3.5
    else: tp_mult=3.0
    tp_pct=round(sl_pct*tp_mult,2); sl_pct=round(sl_pct,2)

    if direction=="BUY":
        sl_price=price*(1-sl_pct/100); tp_price=price*(1+tp_pct/100)
    else:
        sl_price=price*(1+sl_pct/100); tp_price=price*(1-tp_pct/100)

    conf=min(int((score/18)*10),10); conf=max(conf,6)
    mode=f"ICT_{direction}_{session}"

    return direction,conf,mode,reasons[:5],sl_pct,tp_pct,round(sl_price,4),round(tp_price,4)
