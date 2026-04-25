import time
from datetime import datetime
from app.state import state, lock

FEE = 0.001

def get_sizing(balance):
    if balance < 25:    return 20.0, 10
    elif balance < 50:  return 15.0, 8
    elif balance < 100: return 10.0, 6
    elif balance < 200: return 7.0,  5
    elif balance < 500: return 5.0,  4
    else:               return 3.0,  3

def execute(pair, decision, ind, price, strategy_id="S6_MULTI_SIGNAL"):
    with lock:
        balance = state["balance"]
        positions = state["positions"]
    if price <= 0 or balance < 2: return False
    if [p for p in positions if p["pair"]==pair]: return False
    if len(positions) >= 3: return False

    action = decision["action"]
    # Always use explicit prices — fixes TP:undefined
    sl_price  = float(decision.get("sl_price",  price*0.993 if action=="BUY" else price*1.007))
    tp1_price = float(decision.get("tp1_price", price*1.012 if action=="BUY" else price*0.988))
    tp2_price = float(decision.get("tp2_price", price*1.025 if action=="BUY" else price*0.975))

    # Safety checks
    if action=="BUY":
        if sl_price  >= price: sl_price  = price * 0.992
        if tp1_price <= price: tp1_price = price * 1.012
        if tp2_price <= tp1_price: tp2_price = tp1_price * 1.015
    else:
        if sl_price  <= price: sl_price  = price * 1.008
        if tp1_price >= price: tp1_price = price * 0.988
        if tp2_price >= tp1_price: tp2_price = tp1_price * 0.985

    sl_pct  = round(abs(price - sl_price)  / price * 100, 3)
    tp2_pct = round(abs(tp2_price - price) / price * 100, 3)

    risk_pct, max_lev = get_sizing(balance)
    leverage = max(1, min(max_lev, int(decision.get("leverage", 5))))
    margin   = balance * risk_pct / 100
    margin   = min(margin, balance * 0.95)
    notional = margin * leverage
    liq_price = price*(1-0.85/leverage) if action=="BUY" else price*(1+0.85/leverage)
    exp_profit = round(notional * tp2_pct / 100 - notional * FEE, 5)
    exp_loss   = round(notional * sl_pct  / 100 + notional * FEE, 5)

    pos = {
        "id":          f"{pair[:3]}{int(time.time())}",
        "pair":        pair,
        "action":      action,
        "entry":       price,
        "notional":    notional,
        "leverage":    leverage,
        "margin":      margin,
        "sl":          round(sl_price,  4),
        "tp1":         round(tp1_price, 4),
        "tp2":         round(tp2_price, 4),
        "liq":         round(liq_price, 4),
        "sl_pct":      sl_pct,
        "tp_pct":      tp2_pct,
        "tp1_hit":     False,
        "atr":         ind.get("atr", price*0.002),
        "peak":        price,
        "trail_on":    False,
        "be_set":      False,
        "time":        time.time(),
        "time_str":    datetime.now().strftime("%H:%M:%S"),
        "reasoning":   decision.get("reasoning","")[:150],
        "setup_type":  decision.get("setup_type",""),
        "source":      decision.get("source","ai"),
        "strategy_id": strategy_id,
        "confidence":  decision.get("confidence", 5),
        "pnl":         0.0,
        "exp_profit":  exp_profit,
        "exp_loss":    exp_loss,
    }
    with lock:
        state["positions"].append(pos)
        state["balance"] -= margin
        state["last_trade_time"][pair] = time.time()
        state["daily_trades"] += 1
        state["total_trades"] += 1

    rr = round(tp2_pct/sl_pct, 1) if sl_pct > 0 else 0
    print(f"[TRADE] {pair} {action} @${price:.4f} | {leverage}x | "
          f"Margin:${margin:.3f}({risk_pct:.0f}%) Notional:${notional:.2f} | "
          f"SL:${sl_price:.4f} TP2:${tp2_price:.4f} R:R={rr} | "
          f"Est:+${exp_profit:.4f}/-${exp_loss:.4f} | {decision.get('source','?')}")
    return True


def manage_positions():
    with lock:
        positions = state["positions"][:]
    for pos in positions:
        pair = pos["pair"]
        with lock:
            price = state["prices"][pair]
        if price <= 0: continue

        action   = pos["action"]
        entry    = pos["entry"]
        notional = pos["notional"]
        margin   = pos["margin"]
        sl       = pos["sl"]
        tp1      = pos["tp1"]
        tp2      = pos["tp2"]
        liq      = pos["liq"]
        atr      = pos.get("atr", entry*0.002)
        peak     = pos.get("peak", entry)
        t_open   = pos.get("time", time.time())

        raw_pnl = (price-entry)/entry*notional if action=="BUY" else (entry-price)/entry*notional
        pnl_pct = raw_pnl/margin*100 if margin > 0 else 0

        with lock:
            for p in state["positions"]:
                if p["id"]==pos["id"]: p["pnl"]=round(raw_pnl,5)

        # Liquidation
        if (action=="BUY" and price<=liq) or (action=="SELL" and price>=liq):
            _close(pos, "LIQUIDATED", -margin, price); continue

        # Partial TP at TP1
        if not pos.get("tp1_hit", False):
            if (action=="BUY" and price>=tp1) or (action=="SELL" and price<=tp1):
                cn = notional*0.5
                cp = ((tp1-entry)/entry*cn if action=="BUY" else (entry-tp1)/entry*cn) - cn*FEE
                hm = margin*0.5
                with lock:
                    state["balance"] += hm + cp
                    for p in state["positions"]:
                        if p["id"]==pos["id"]:
                            p["notional"]-=cn; p["margin"]-=hm
                            p["tp1_hit"]=True; p["sl"]=entry; p["be_set"]=True
                notional-=cn; margin-=hm; sl=entry
                print(f"[TP1] {pair} 50% @${tp1:.4f} +${cp:.5f}"); continue

        # Breakeven
        if not pos.get("be_set",False) and pnl_pct > 0.5*pos["leverage"]:
            be_p = entry*(1+FEE*2.2) if action=="BUY" else entry*(1-FEE*2.2)
            if (action=="BUY" and be_p>sl) or (action=="SELL" and be_p<sl):
                with lock:
                    for p in state["positions"]:
                        if p["id"]==pos["id"]: p["sl"]=round(be_p,4); p["be_set"]=True
                sl=be_p

        # Trail
        if not pos.get("trail_on",False) and pnl_pct > atr/entry*100*pos["leverage"]*1.5:
            with lock:
                for p in state["positions"]:
                    if p["id"]==pos["id"]: p["trail_on"]=True
        if pos.get("trail_on",False):
            td=atr*1.2
            if action=="BUY" and price>peak:
                ns=price-td
                if ns>sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"]==pos["id"]: p["sl"]=round(ns,4); p["peak"]=price
                    sl=ns; peak=price
            elif action=="SELL" and price<peak:
                ns=price+td
                if ns<sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"]==pos["id"]: p["sl"]=round(ns,4); p["peak"]=price
                    sl=ns; peak=price

        # Exits
        er=None; ep=0.0
        if action=="BUY" and price>=tp2:   er="TP2"; ep=(tp2-entry)/entry*notional-notional*FEE
        elif action=="SELL" and price<=tp2: er="TP2"; ep=(entry-tp2)/entry*notional-notional*FEE
        elif action=="BUY" and price<=sl:  er="SL";  ep=(sl-entry)/entry*notional-notional*FEE
        elif action=="SELL" and price>=sl: er="SL";  ep=(entry-sl)/entry*notional-notional*FEE
        elif time.time()-t_open>14400:     er="TIME"; ep=raw_pnl-notional*FEE
        if er: _close(pos, er, ep, price)


def _close(pos, reason, pnl, cp):
    margin = pos["margin"]
    rec = {
        "id": pos["id"], "pair": pos["pair"], "action": pos["action"],
        "entry": pos["entry"], "exit": cp,
        "notional": round(pos["notional"],5), "pnl": round(pnl,5),
        "pnl_pct": round(pnl/margin*100,2) if margin>0 else 0,
        "reason": reason, "setup_type": pos.get("setup_type",""),
        "reasoning": pos.get("reasoning",""), "source": pos.get("source","?"),
        "strategy_id": pos.get("strategy_id","?"),
        "confidence": pos.get("confidence",5), "leverage": pos.get("leverage",1),
        "margin": round(margin,4),
        "duration": round((time.time()-pos["time"])/60,1),
        "time": pos.get("time_str",""), "exit_time": datetime.now().strftime("%H:%M:%S"),
        "won": pnl > 0,
    }
    with lock:
        state["balance"] += margin + pnl
        if state["balance"] > state["peak_balance"]: state["peak_balance"]=state["balance"]
        open_m = sum(p["margin"] for p in state["positions"] if p["id"]!=pos["id"])
        dd = max(0,(state["peak_balance"]-state["balance"]-open_m)/state["peak_balance"]*100)
        if dd > state["max_drawdown"]: state["max_drawdown"]=round(dd,2)
        if pnl>0: state["winning_trades"]+=1; state["daily_wins"]+=1
        else:     state["losing_trades"]+=1;  state["daily_loss"]+=abs(pnl)
        state["total_pnl"] = state["balance"]-state["initial_balance"]
        state["trades"].insert(0,rec)
        if len(state["trades"])>200: state["trades"].pop()
        state["positions"]=[p for p in state["positions"] if p["id"]!=pos["id"]]
        state["equity_curve"].append({"t":datetime.now().strftime("%H:%M"),"v":round(state["balance"],5)})
        if len(state["equity_curve"])>300: state["equity_curve"].pop(1)
        # Update strategy stats
        sid = pos.get("strategy_id","?")
        if sid in state["strategies"]:
            state["strategies"][sid]["trades"] += 1
            if pnl > 0:
                state["strategies"][sid]["wins"] += 1
                prev_aw = state["strategies"][sid].get("avg_win",0)
                w = state["strategies"][sid]["wins"]
                state["strategies"][sid]["avg_win"] = round((prev_aw*(w-1)+pnl)/w, 5)
            else:
                state["strategies"][sid]["losses"] += 1
                prev_al = state["strategies"][sid].get("avg_loss",0)
                l = state["strategies"][sid]["losses"]
                state["strategies"][sid]["avg_loss"] = round((prev_al*(l-1)+pnl)/l, 5)
            t = state["strategies"][sid]["trades"]
            w = state["strategies"][sid]["wins"]
            state["strategies"][sid]["win_rate"] = round(w/t*100,1) if t>0 else 0
            state["strategies"][sid]["total_pnl"] = round(
                state["strategies"][sid].get("total_pnl",0)+pnl, 5)
    emoji="✅" if pnl>0 else "❌"
    print(f"{emoji}[{reason}] {pos['pair']} {pos['action']} @${cp:.4f} "
          f"PnL:${pnl:+.5f}({rec['pnl_pct']:+.1f}%) {rec['duration']}min "
          f"strat:{rec['strategy_id']} src:{rec['source']}")


def daily_reset():
    import datetime as dt
    h = dt.datetime.utcnow().hour
    with lock:
        if h==0 and state.get("daily_reset_hour")!=0:
            state["daily_trades"]=0; state["daily_loss"]=0.0
            state["daily_wins"]=0;   state["daily_reset_hour"]=0
        elif h!=0: state["daily_reset_hour"]=h
