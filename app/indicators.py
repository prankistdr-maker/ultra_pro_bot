def compute(candles):
    if not candles or len(candles) < 20:
        return {}
    closes=[c["c"] for c in candles]; highs=[c["h"] for c in candles]
    lows=[c["l"] for c in candles]; vols=[c["v"] for c in candles]
    price=closes[-1]

    def ema(vals,p):
        if len(vals)<p: return vals[-1]
        k=2/(p+1); r=sum(vals[:p])/p
        for v in vals[p:]: r=v*k+r*(1-k)
        return r

    e9=ema(closes,9); e21=ema(closes,21)
    e50=ema(closes,50) if len(closes)>=50 else closes[-1]
    gains=[max(closes[i]-closes[i-1],0) for i in range(1,len(closes))]
    losses=[max(closes[i-1]-closes[i],0) for i in range(1,len(closes))]
    ag=sum(gains[-14:])/14; al=sum(losses[-14:])/14
    rsi=round(100-(100/(1+ag/al)),1) if al>0 else 100
    e12=ema(closes,12); e26=ema(closes,26); macd=round(e12-e26,4)
    trs=[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1]))
         for i in range(1,len(candles))]
    atr=round(sum(trs[-14:])/14,4); atr_pct=round(atr/price*100,3)
    typical=[(highs[i]+lows[i]+closes[i])/3 for i in range(len(candles))]
    vol_sum=sum(vols)
    vwap=round(sum(t*v for t,v in zip(typical,vols))/vol_sum,2) if vol_sum>0 else price
    avg_vol=sum(vols[-20:])/20
    vol_ratio=round(vols[-1]/avg_vol,2) if avg_vol>0 else 1
    swing_high=round(max(highs[-20:]),4); swing_low=round(min(lows[-20:]),4)
    prev_high=max(highs[-20:-3]); prev_low=min(lows[-20:-3])
    liq_sweep_bull=lows[-1]<prev_low and closes[-1]>prev_low and closes[-1]>closes[-2]
    liq_sweep_bear=highs[-1]>prev_high and closes[-1]<prev_high and closes[-1]<closes[-2]
    sh=max(highs[-8:-2]); sl_lvl=min(lows[-8:-2])
    choch_bull=closes[-1]>sh and closes[-2]<=sh
    choch_bear=closes[-1]<sl_lvl and closes[-2]>=sl_lvl
    fvg_bull=len(candles)>=3 and lows[-1]>highs[-3]
    fvg_bear=len(candles)>=3 and highs[-1]<lows[-3]
    ob_bull=ob_bear=False
    for i in range(len(candles)-5,len(candles)-2):
        if i<1: continue
        if closes[i]<candles[i]["o"] and closes[i+1]>closes[i]: ob_bull=True
        if closes[i]>candles[i]["o"] and closes[i+1]<closes[i]: ob_bear=True
    hh=max(highs[-3:])>max(highs[-6:-3]) if len(highs)>=6 else False
    hl=min(lows[-3:])>min(lows[-6:-3]) if len(lows)>=6 else False
    ll=min(lows[-3:])<min(lows[-6:-3]) if len(lows)>=6 else False
    lh=max(highs[-3:])<max(highs[-6:-3]) if len(highs)>=6 else False
    if hh and hl and e9>e21: trend="STRONG_BULL"
    elif hh and hl: trend="BULL"
    elif ll and lh: trend="BEAR"
    elif e9>e21: trend="RANGING_BULL"
    else: trend="RANGING_BEAR"
    rng=swing_high-swing_low
    zone_pct=round((price-swing_low)/rng,2) if rng>0 else 0.5
    pd_zone="discount" if zone_pct<0.45 else("premium" if zone_pct>0.55 else "equilibrium")
    liq_above=round(max(highs[-30:-3]) if len(highs)>=30 else swing_high,4)
    liq_below=round(min(lows[-30:-3]) if len(lows)>=30 else swing_low,4)
    # Bollinger Bands
    bb_mid=sum(closes[-20:])/20
    bb_std=(sum((c-bb_mid)**2 for c in closes[-20:])/20)**0.5
    bb_upper=round(bb_mid+2*bb_std,4); bb_lower=round(bb_mid-2*bb_std,4)
    return {
        "price":round(price,4),"ema9":round(e9,2),"ema21":round(e21,2),"ema50":round(e50,2),
        "ema_bull":e9>e21,"ema_strong_bull":e9>e21>e50,
        "rsi":rsi,"macd":macd,"atr":atr,"atr_pct":atr_pct,
        "vwap":vwap,"above_vwap":price>vwap,
        "vol_ratio":vol_ratio,"high_volume":vol_ratio>1.5,
        "swing_high":swing_high,"swing_low":swing_low,
        "liq_above":liq_above,"liq_below":liq_below,
        "liq_sweep_bull":liq_sweep_bull,"liq_sweep_bear":liq_sweep_bear,
        "choch_bull":choch_bull,"choch_bear":choch_bear,
        "fvg_bull":fvg_bull,"fvg_bear":fvg_bear,
        "ob_bull":ob_bull,"ob_bear":ob_bear,
        "trend":trend,"pd_zone":pd_zone,"zone_pct":zone_pct,
        "hh":hh,"hl":hl,"ll":ll,"lh":lh,
        "prev_high":round(prev_high,4),"prev_low":round(prev_low,4),
        "bb_upper":bb_upper,"bb_lower":bb_lower,"bb_mid":round(bb_mid,4),
    }
