"""
AdaptiveBot PRO - Execution Engine v3
Based on research:
- Kelly Criterion position sizing (Berlekamp/Renaissance)
- Breakeven stop after 0.6% profit (never give back more than half)
- Trailing activates after 0.4% (give trade room to breathe)
- TIME exit only if profitable (never lock in losses)
- MAX_TIME 90 minutes (give TP time to hit)
- 4% daily loss hard stop (professional risk management)
"""
import time
from datetime import datetime
from app.state import state, lock
 
FEE_RATE  = 0.001    # 0.1% per side = 0.2% round trip
MIN_TRADE = 20       # Minimum $20
RISK_PCT  = 0.015    # 1.5% risk per trade (Kelly-inspired conservative)
MAX_TIME  = 5400     # 90 minutes (was 45min — too short for TP to hit)
 
 
def execute(action, sl_pct, tp_pct, confidence, reasons, mode):
    """Open position with research-based sizing"""
    with lock:
        price     = state["price"]
        balance   = state["balance"]
        positions = state["positions"]
 
    if price <= 0 or balance < 50 or len(positions) >= 1:
        return
 
    # KELLY CRITERION position sizing (Renaissance uses this)
    # Risk exactly RISK_PCT of balance
    # Position size so SL loss = risk_amount
    risk_amount = balance * RISK_PCT
    sl_dollar   = price * sl_pct / 100
    units       = risk_amount / sl_dollar if sl_dollar > 0 else 0
    trade_value = units * price
    trade_value = min(trade_value, balance * 0.25)
    trade_value = max(trade_value, MIN_TRADE)
    if trade_value > balance * 0.9:
        return
 
    entry_fee = trade_value * FEE_RATE
    sl_price  = price * (1 - sl_pct/100) if action == "BUY" else price * (1 + sl_pct/100)
    tp_price  = price * (1 + tp_pct/100) if action == "BUY" else price * (1 - tp_pct/100)
 
    position = {
        "id":              f"T{int(time.time())}",
        "action":          action,
        "entry":           price,
        "amount":          trade_value,
        "sl":              round(sl_price, 2),
        "tp":              round(tp_price, 2),
        "sl_pct":          sl_pct,
        "tp_pct":          tp_pct,
        "peak":            price,
        "trail_activated": False,
        "breakeven_set":   False,
        "time":            time.time(),
        "time_str":        datetime.now().strftime("%H:%M:%S"),
        "confidence":      confidence,
        "mode":            mode,
        "reasons":         reasons[:4],
        "status":          "OPEN",
        "fee_paid":        entry_fee,
        "pnl":             0.0,
    }
 
    with lock:
        state["positions"].append(position)
        state["balance"]         -= (trade_value + entry_fee)
        state["last_trade_time"]  = time.time()
        state["daily_trades"]    += 1
        state["total_trades"]    += 1
 
    print(f"[TRADE] {action} @ ${price:,.2f} | SL:{sl_pct}%(${sl_price:,.0f}) TP:{tp_pct}%(${tp_price:,.0f}) | ${trade_value:.0f} | Conf:{confidence}/10 | {mode}")
 
 
def manage_positions():
    """
    Professional position management:
    1. Move to breakeven after 0.6% profit (never lose on a winner)
    2. Trail after 0.4% profit (lock profits as price moves)
    3. TP/SL exits
    4. TIME exit ONLY if profitable (never force a loss)
    """
    with lock:
        price     = state["price"]
        positions = state["positions"][:]
 
    if price <= 0 or not positions:
        return
 
    for pos in positions:
        action    = pos["action"]
        entry     = pos["entry"]
        amount    = pos["amount"]
        sl        = pos["sl"]
        tp        = pos["tp"]
        sl_pct    = pos.get("sl_pct", 0.5)
        peak      = pos.get("peak", entry)
        time_open = pos.get("time", time.time())
 
        # Live PnL
        raw_pnl  = (price-entry)/entry*amount if action=="BUY" else (entry-price)/entry*amount
        pnl_pct  = raw_pnl / amount * 100
 
        with lock:
            for p in state["positions"]:
                if p["id"] == pos["id"]:
                    p["pnl"] = round(raw_pnl, 2)
 
        trail = pos.get("trail_activated", False)
        be    = pos.get("breakeven_set", False)
 
        # BREAKEVEN after 0.6% profit (never give back more than half a win)
        if not be and pnl_pct > 0.6:
            be_price = entry*(1+FEE_RATE*2) if action=="BUY" else entry*(1-FEE_RATE*2)
            if (action=="BUY" and be_price>sl) or (action=="SELL" and be_price<sl):
                with lock:
                    for p in state["positions"]:
                        if p["id"] == pos["id"]:
                            p["sl"] = round(be_price, 2)
                            p["breakeven_set"] = True
                sl = be_price; be = True
                print(f"[BREAKEVEN] {pos['id']} SL→${be_price:,.2f}")
 
        # TRAILING STOP after 0.4% profit
        if not trail and pnl_pct > 0.4:
            with lock:
                for p in state["positions"]:
                    if p["id"] == pos["id"]:
                        p["trail_activated"] = True
            trail = True
 
        if trail:
            if action == "BUY" and price > peak:
                new_sl = price - price*sl_pct/100
                if new_sl > sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"] = round(new_sl, 2); p["peak"] = price
                    sl = new_sl; peak = price
 
            elif action == "SELL" and price < peak:
                new_sl = price + price*sl_pct/100
                if new_sl < sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"] = round(new_sl, 2); p["peak"] = price
                    sl = new_sl; peak = price
 
        # EXIT CONDITIONS
        exit_reason = None
        exit_pnl    = 0.0
 
        if action=="BUY"  and price>=tp:
            exit_reason="TP"; exit_pnl=(tp-entry)/entry*amount - amount*FEE_RATE
        elif action=="SELL" and price<=tp:
            exit_reason="TP"; exit_pnl=(entry-tp)/entry*amount - amount*FEE_RATE
        elif action=="BUY"  and price<=sl:
            exit_reason="SL"; exit_pnl=(sl-entry)/entry*amount - amount*FEE_RATE
        elif action=="SELL" and price>=sl:
            exit_reason="SL"; exit_pnl=(entry-sl)/entry*amount - amount*FEE_RATE
        elif time.time()-time_open > MAX_TIME:
            if raw_pnl > amount*FEE_RATE:  # Only exit TIME if profitable
                exit_reason="TIME"; exit_pnl=raw_pnl - amount*FEE_RATE
            # If losing: let TP or SL handle it — don't force a loss
        # Emergency: losing 3x SL after 3 hours = exit to protect capital
        elif time.time()-time_open > 10800 and pnl_pct < -(sl_pct*3):
            exit_reason="EMERGENCY"; exit_pnl=raw_pnl - amount*FEE_RATE
 
        if exit_reason:
            _close(pos, exit_reason, exit_pnl, price)
 
 
def _close(pos, reason, pnl, close_price):
    amount = pos["amount"]
    record = {
        "id":         pos["id"],
        "action":     pos["action"],
        "entry":      pos["entry"],
        "exit":       close_price,
        "amount":     round(amount, 2),
        "pnl":        round(pnl, 4),
        "pnl_pct":    round(pnl/amount*100, 2),
        "reason":     reason,
        "mode":       pos.get("mode",""),
        "confidence": pos.get("confidence",0),
        "reasons":    pos.get("reasons",[]),
        "duration":   round((time.time()-pos["time"])/60, 1),
        "time":       pos.get("time_str",""),
        "exit_time":  datetime.now().strftime("%H:%M:%S"),
        "won":        pnl > 0,
    }
    emoji = "✅" if pnl > 0 else "❌"
    with lock:
        state["balance"] += amount + pnl
        if state["balance"] > state["peak_balance"]:
            state["peak_balance"] = state["balance"]
        dd = (state["peak_balance"]-state["balance"])/state["peak_balance"]*100
        if dd > state["max_drawdown"]:
            state["max_drawdown"] = round(dd, 2)
        if pnl > 0:
            state["winning_trades"] += 1; state["daily_wins"] += 1
        else:
            state["losing_trades"] += 1; state["daily_loss"] += abs(pnl)
        state["total_pnl"] = state["balance"] - state["initial_balance"]
        state["trades"].insert(0, record)
        if len(state["trades"]) > 200: state["trades"].pop()
        state["positions"] = [p for p in state["positions"] if p["id"] != pos["id"]]
    print(f"{emoji} [CLOSE] {pos['action']} {reason} @ ${close_price:,.2f} | PnL:${pnl:+.2f} ({record['pnl_pct']:+.1f}%) | {record['duration']}min")
 
 
def daily_reset():
    import datetime as dt
    hour = dt.datetime.utcnow().hour
    with lock:
        if hour == 0 and state.get("daily_reset_hour") != 0:
            state["daily_trades"]=0; state["daily_loss"]=0.0
            state["daily_wins"]=0;   state["daily_reset_hour"]=0
        elif hour != 0:
            state["daily_reset_hour"] = hour
 
