import time
from datetime import datetime
from app.state import state, lock

FEE = 0.001

def execute(pair, decision, ind, price):
    with lock:
        balance   = state["balance"]
        positions = state["positions"]

    if price <= 0 or balance < 2:
        return False
    if [p for p in positions if p["pair"] == pair]:
        return False
    if len(positions) >= 3:
        return False

    action   = decision["action"]
    sl_pct   = decision["sl_pct"]
    tp_pct   = decision["tp_pct"]
    risk_pct = decision["risk_pct"]

    # Size: risk risk_pct% of balance
    risk_amt = balance * risk_pct / 100
    sl_dist  = price * sl_pct / 100
    size     = (risk_amt / sl_dist) * price if sl_dist > 0 else balance * 0.05
    size     = min(size, balance * 0.3)
    size     = max(size, 1.0)
    if size > balance * 0.95:
        return False

    sl_price = price*(1-sl_pct/100) if action=="BUY" else price*(1+sl_pct/100)
    tp_price = price*(1+tp_pct/100) if action=="BUY" else price*(1-tp_pct/100)

    pos = {
        "id":         f"{pair[:3]}{int(time.time())}",
        "pair":       pair,
        "action":     action,
        "entry":      price,
        "amount":     size,
        "sl":         round(sl_price, 4),
        "tp":         round(tp_price, 4),
        "sl_pct":     sl_pct,
        "tp_pct":     tp_pct,
        "atr":        ind.get("atr", price*0.002),
        "peak":       price,
        "trail_on":   False,
        "be_set":     False,
        "time":       time.time(),
        "time_str":   datetime.now().strftime("%H:%M:%S"),
        "reasoning":  decision.get("reasoning", ""),
        "setup_type": decision.get("setup_type", ""),
        "confidence": decision.get("confidence", 5),
        "pnl":        0.0,
    }

    with lock:
        state["positions"].append(pos)
        state["balance"]              -= (size + size*FEE)
        state["last_trade_time"][pair] = time.time()
        state["daily_trades"]         += 1
        state["total_trades"]         += 1

    rr = round(tp_pct/sl_pct, 1)
    print(f"[TRADE] {pair} {action} @${price:.4f} SL:{sl_pct}% TP:{tp_pct}% R:R={rr} size=${size:.4f}")
    print(f"        Setup: {decision.get('setup_type','')} | {decision.get('reasoning','')[:80]}")
    return True


def manage_positions():
    with lock:
        positions = state["positions"][:]

    for pos in positions:
        pair = pos["pair"]
        with lock:
            price = state["prices"][pair]
        if price <= 0:
            continue

        action = pos["action"]
        entry  = pos["entry"]
        amount = pos["amount"]
        sl     = pos["sl"]
        tp     = pos["tp"]
        atr    = pos.get("atr", entry*0.002)
        peak   = pos.get("peak", entry)
        t_open = pos.get("time", time.time())

        raw_pnl = (price-entry)/entry*amount if action=="BUY" else (entry-price)/entry*amount
        pnl_pct = raw_pnl/amount*100

        with lock:
            for p in state["positions"]:
                if p["id"] == pos["id"]:
                    p["pnl"] = round(raw_pnl, 5)

        be    = pos.get("be_set", False)
        trail = pos.get("trail_on", False)

        # Breakeven after 0.5% profit
        if not be and pnl_pct > 0.5:
            be_p = entry*(1+FEE*2.2) if action=="BUY" else entry*(1-FEE*2.2)
            if (action=="BUY" and be_p>sl) or (action=="SELL" and be_p<sl):
                with lock:
                    for p in state["positions"]:
                        if p["id"]==pos["id"]:
                            p["sl"] = round(be_p, 4); p["be_set"] = True
                sl = be_p; be = True

        # Trail after 0.4% profit — ATR distance
        if not trail and pnl_pct > 0.4:
            with lock:
                for p in state["positions"]:
                    if p["id"]==pos["id"]: p["trail_on"] = True
            trail = True

        if trail:
            td = atr * 1.5
            if action=="BUY" and price>peak:
                ns = price-td
                if ns>sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"]==pos["id"]: p["sl"]=round(ns,4); p["peak"]=price
                    sl=ns; peak=price
            elif action=="SELL" and price<peak:
                ns = price+td
                if ns<sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"]==pos["id"]: p["sl"]=round(ns,4); p["peak"]=price
                    sl=ns; peak=price

        # Exits
        er = None; ep = 0.0
        if action=="BUY" and price>=tp:   er="TP"; ep=(tp-entry)/entry*amount-amount*FEE
        elif action=="SELL" and price<=tp: er="TP"; ep=(entry-tp)/entry*amount-amount*FEE
        elif action=="BUY" and price<=sl:  er="SL"; ep=(sl-entry)/entry*amount-amount*FEE
        elif action=="SELL" and price>=sl: er="SL"; ep=(entry-sl)/entry*amount-amount*FEE
        elif time.time()-t_open>7200 and raw_pnl>amount*FEE: er="TIME"; ep=raw_pnl-amount*FEE
        elif time.time()-t_open>14400 and pnl_pct<-(pos["sl_pct"]*3): er="EMERGENCY"; ep=raw_pnl-amount*FEE

        if er:
            _close(pos, er, ep, price)


def _close(pos, reason, pnl, cp):
    amt = pos["amount"]
    rec = {
        "id": pos["id"], "pair": pos["pair"], "action": pos["action"],
        "entry": pos["entry"], "exit": cp, "amount": round(amt,5),
        "pnl": round(pnl,5), "pnl_pct": round(pnl/amt*100,3),
        "reason": reason,
        "setup_type": pos.get("setup_type",""),
        "reasoning":  pos.get("reasoning",""),
        "confidence": pos.get("confidence",5),
        "duration": round((time.time()-pos["time"])/60,1),
        "time": pos.get("time_str",""),
        "exit_time": datetime.now().strftime("%H:%M:%S"),
        "won": pnl > 0,
    }
    emoji = "✅" if pnl>0 else "❌"
    with lock:
        state["balance"] += amt + pnl
        if state["balance"] > state["peak_balance"]:
            state["peak_balance"] = state["balance"]
        open_amt = sum(p["amount"] for p in state["positions"] if p["id"]!=pos["id"])
        eff = state["balance"] + open_amt
        dd = max(0, (state["peak_balance"]-eff)/state["peak_balance"]*100)
        if dd > state["max_drawdown"]: state["max_drawdown"] = round(dd,2)
        if pnl>0: state["winning_trades"]+=1; state["daily_wins"]+=1
        else: state["losing_trades"]+=1; state["daily_loss"]+=abs(pnl)
        state["total_pnl"] = state["balance"]-state["initial_balance"]
        state["trades"].insert(0, rec)
        if len(state["trades"])>200: state["trades"].pop()
        state["positions"] = [p for p in state["positions"] if p["id"]!=pos["id"]]
        state["equity_curve"].append({"t":datetime.now().strftime("%H:%M"),"v":round(state["balance"],5)})
        if len(state["equity_curve"])>300: state["equity_curve"].pop(1)
    print(f"{emoji} [{reason}] {pos['pair']} {pos['action']} @${cp:.4f} PnL:${pnl:+.5f}({rec['pnl_pct']:+.2f}%) {rec['duration']}min")


def daily_reset():
    import datetime as dt
    h = dt.datetime.utcnow().hour
    with lock:
        if h==0 and state.get("daily_reset_hour")!=0:
            state["daily_trades"]=0; state["daily_loss"]=0.0
            state["daily_wins"]=0;   state["daily_reset_hour"]=0
        elif h!=0:
            state["daily_reset_hour"]=h
