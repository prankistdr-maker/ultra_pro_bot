"""Execution v6 - Kelly sizing, proper SL/TP, tight trailing"""
import time
from datetime import datetime
from app.state import state, lock

FEE = 0.001
MIN_TRADE = 2
MAX_TIME  = 5400   # 90 min

def kelly_size(balance, sl_pct, win_rate=0.68, rr=3.5):
    p=win_rate; q=1-p; b=rr
    k = max(0, (p*b - q) / b) * 0.4  # 40% Kelly
    k = max(0.01, min(k, 0.025))
    risk = balance * k
    sl_d = balance * sl_pct / 100
    size = (risk / sl_d) * balance if sl_d > 0 else balance * 0.05
    return round(max(min(size, balance*0.3), MIN_TRADE), 5)

def execute(pair, action, sl_pct, tp_pct, sl_price, tp_price, conf, reasons, mode, ind):
    with lock:
        price = state["prices"][pair]; balance = state["balance"]; positions = state["positions"]
    if price<=0 or balance<2: return
    if [p for p in positions if p["pair"]==pair] or len(positions)>=7: return
    size = kelly_size(balance, sl_pct)
    if size > balance*0.9: return
    if sl_price<=0: sl_price = price*(1-sl_pct/100) if action=="BUY" else price*(1+sl_pct/100)
    if tp_price<=0: tp_price = price*(1+tp_pct/100) if action=="BUY" else price*(1-tp_pct/100)
    atr = ind.get("atr", price*0.002)
    pos = {
        "id": f"{pair[:3]}{int(time.time())}", "pair": pair, "action": action,
        "entry": price, "amount": size,
        "sl": round(sl_price,4), "tp": round(tp_price,4),
        "sl_pct": round(abs(price-sl_price)/price*100,3),
        "tp_pct": round(abs(tp_price-price)/price*100,3),
        "atr": atr, "peak": price, "trail_on": False, "be_set": False,
        "time": time.time(), "time_str": datetime.now().strftime("%H:%M:%S"),
        "confidence": conf, "mode": mode, "reasons": reasons[:4], "pnl": 0.0,
    }
    with lock:
        state["positions"].append(pos)
        state["balance"] -= (size + size*FEE)
        state["last_trade_time"][pair] = time.time()
        state["daily_trades"] += 1; state["total_trades"] += 1
    rr = round(abs(tp_price-price)/abs(sl_price-price),1) if sl_price!=price else 0
    print(f"[TRADE] {pair} {action} @${price:.3f} SL:${sl_price:.3f}({pos['sl_pct']}%) TP:${tp_price:.3f} R:R{rr} ${size:.4f}")

def manage_positions():
    with lock: positions = state["positions"][:]
    for pos in positions:
        pair = pos["pair"]
        with lock: price = state["prices"][pair]
        if price<=0: continue
        action=pos["action"]; entry=pos["entry"]; amount=pos["amount"]
        sl=pos["sl"]; tp=pos["tp"]; atr=pos.get("atr",entry*0.002)
        peak=pos.get("peak",entry); t_open=pos.get("time",time.time())
        raw_pnl=(price-entry)/entry*amount if action=="BUY" else (entry-price)/entry*amount
        pnl_pct=raw_pnl/amount*100
        with lock:
            for p in state["positions"]:
                if p["id"]==pos["id"]: p["pnl"]=round(raw_pnl,5)
        be=pos.get("be_set",False); trail=pos.get("trail_on",False)
        if not be and pnl_pct>0.5:
            be_p=entry*(1+FEE*2.2) if action=="BUY" else entry*(1-FEE*2.2)
            if (action=="BUY" and be_p>sl) or (action=="SELL" and be_p<sl):
                with lock:
                    for p in state["positions"]:
                        if p["id"]==pos["id"]: p["sl"]=round(be_p,4); p["be_set"]=True
                sl=be_p; be=True
        if not trail and pnl_pct>0.4:
            with lock:
                for p in state["positions"]:
                    if p["id"]==pos["id"]: p["trail_on"]=True
            trail=True
        if trail:
            td=atr*1.5
            if action=="BUY" and price>peak:
                nsl=price-td
                if nsl>sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"]==pos["id"]: p["sl"]=round(nsl,4); p["peak"]=price
                    sl=nsl; peak=price
            elif action=="SELL" and price<peak:
                nsl=price+td
                if nsl<sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"]==pos["id"]: p["sl"]=round(nsl,4); p["peak"]=price
                    sl=nsl; peak=price
        ex=None; ep=0.0
        if action=="BUY" and price>=tp: ex="TP"; ep=(tp-entry)/entry*amount-amount*FEE
        elif action=="SELL" and price<=tp: ex="TP"; ep=(entry-tp)/entry*amount-amount*FEE
        elif action=="BUY" and price<=sl: ex="SL"; ep=(sl-entry)/entry*amount-amount*FEE
        elif action=="SELL" and price>=sl: ex="SL"; ep=(entry-sl)/entry*amount-amount*FEE
        elif time.time()-t_open>MAX_TIME and raw_pnl>amount*FEE: ex="TIME"; ep=raw_pnl-amount*FEE
        elif time.time()-t_open>10800 and pnl_pct<-(pos["sl_pct"]*2.5): ex="EMERGENCY"; ep=raw_pnl-amount*FEE
        if ex: _close(pos,ex,ep,price)

def _close(pos,reason,pnl,cp):
    amt=pos["amount"]
    rec={"id":pos["id"],"pair":pos["pair"],"action":pos["action"],
         "entry":pos["entry"],"exit":cp,"amount":round(amt,5),
         "pnl":round(pnl,5),"pnl_pct":round(pnl/amt*100,3),
         "reason":reason,"mode":pos.get("mode",""),
         "confidence":pos.get("confidence",0),"reasons":pos.get("reasons",[]),
         "duration":round((time.time()-pos["time"])/60,1),
         "time":pos.get("time_str",""),"exit_time":datetime.now().strftime("%H:%M:%S"),
         "won":pnl>0}
    emoji="✅" if pnl>0 else "❌"
    with lock:
        state["balance"]+=amt+pnl
        if state["balance"]>state["peak_balance"]: state["peak_balance"]=state["balance"]
        open_amt=sum(p["amount"] for p in state["positions"] if p["id"]!=pos["id"])
        eff_bal=state["balance"]+open_amt
        dd=(state["peak_balance"]-eff_bal)/state["peak_balance"]*100
        if dd>state["max_drawdown"]: state["max_drawdown"]=round(max(0,dd),2)
        if pnl>0: state["winning_trades"]+=1; state["daily_wins"]+=1
        else: state["losing_trades"]+=1; state["daily_loss"]+=abs(pnl)
        state["total_pnl"]=state["balance"]-state["initial_balance"]
        state["trades"].insert(0,rec)
        if len(state["trades"])>200: state["trades"].pop()
        state["positions"]=[p for p in state["positions"] if p["id"]!=pos["id"]]
        state["equity_curve"].append({"t":datetime.now().strftime("%H:%M"),"v":round(state["balance"],5)})
        if len(state["equity_curve"])>300: state["equity_curve"].pop(1)
    print(f"{emoji} [{reason}] {pos['pair']} {pos['action']} @${cp:.3f} PnL:${pnl:+.5f}({rec['pnl_pct']:+.2f}%) {rec['duration']}min")

def daily_reset():
    import datetime as dt
    h=dt.datetime.utcnow().hour
    with lock:
        if h==0 and state.get("daily_reset_hour")!=0:
            state["daily_trades"]=0; state["daily_loss"]=0.0
            state["daily_wins"]=0;   state["daily_reset_hour"]=0
        elif h!=0: state["daily_reset_hour"]=h
