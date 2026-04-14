"""
Execution Engine v5
- Kelly Criterion position sizing
- SL/TP passed from engine (actual SMC levels)
- Breakeven at 0.5% profit
- ATR trailing (1.5x ATR distance)
- Emergency exit after 3h
"""
import time
from datetime import datetime
from app.state import state, lock

FEE_RATE  = 0.001
MIN_TRADE = 2
MAX_TIME  = 5400   # 90 min
WIN_RATE  = 0.65   # Expected win rate for Kelly (conservative)
AVG_RR    = 3.0    # Expected R:R ratio


def kelly_size(balance, sl_pct):
    """
    Kelly Criterion: optimal bet size
    f = (p * b - q) / b
    p = win probability, q = 1-p, b = R:R ratio
    Using half-Kelly for safety
    """
    p = WIN_RATE; q = 1 - p; b = AVG_RR
    kelly = (p * b - q) / b
    half_kelly = kelly * 0.5   # Half Kelly = safer
    half_kelly = max(0.01, min(half_kelly, 0.03))  # 1-3% of balance

    risk_amount = balance * half_kelly
    sl_dollar   = balance * sl_pct / 100 if sl_pct > 0 else balance * 0.005
    position    = (risk_amount / sl_dollar) * balance if sl_dollar > 0 else balance * 0.05

    position = min(position, balance * 0.3)
    position = max(position, MIN_TRADE)
    return round(position, 4)


def execute(pair, action, sl_pct, tp_pct, sl_price, tp_price, confidence, reasons, mode, ind):
    with lock:
        price     = state["prices"][pair]
        balance   = state["balance"]
        positions = state["positions"]

    if price <= 0 or balance < 2:
        return
    if len([p for p in positions if p["pair"] == pair]) > 0:
        return
    if len(positions) >= 2:
        return

    trade_value = kelly_size(balance, sl_pct)
    if trade_value > balance * 0.9:
        return

    # Use engine-calculated SL/TP (at actual SMC levels)
    # Fallback to % if prices not valid
    if sl_price <= 0 or tp_price <= 0:
        sl_price = price*(1-sl_pct/100) if action=="BUY" else price*(1+sl_pct/100)
        tp_price = price*(1+tp_pct/100) if action=="BUY" else price*(1-tp_pct/100)

    entry_fee = trade_value * FEE_RATE
    atr       = ind.get("atr", price * 0.002)

    position = {
        "id":        f"{pair[:3]}{int(time.time())}",
        "pair":      pair,
        "action":    action,
        "entry":     price,
        "amount":    trade_value,
        "sl":        round(sl_price, 4),
        "tp":        round(tp_price, 4),
        "sl_pct":    round(abs(price-sl_price)/price*100, 3),
        "tp_pct":    round(abs(tp_price-price)/price*100, 3),
        "atr":       atr,
        "peak":      price,
        "trail_on":  False,
        "be_set":    False,
        "time":      time.time(),
        "time_str":  datetime.now().strftime("%H:%M:%S"),
        "confidence": confidence,
        "mode":      mode,
        "reasons":   reasons[:4],
        "pnl":       0.0,
        "fee":       entry_fee,
    }

    with lock:
        state["positions"].append(position)
        state["balance"]              -= (trade_value + entry_fee)
        state["last_trade_time"][pair] = time.time()
        state["daily_trades"]         += 1
        state["total_trades"]         += 1

    rr = round(abs(tp_price-price)/abs(sl_price-price), 1) if sl_price != price else 0
    print(f"[TRADE] {pair} {action} @${price:,.3f} | SL:${sl_price:,.3f} TP:${tp_price:,.3f} | R:R {rr} | ${trade_value:.3f}")


def manage_positions():
    with lock:
        positions = state["positions"][:]

    for pos in positions:
        pair  = pos["pair"]
        with lock:
            price = state["prices"][pair]
        if price <= 0:
            continue

        action = pos["action"]
        entry  = pos["entry"]
        amount = pos["amount"]
        sl     = pos["sl"]
        tp     = pos["tp"]
        atr    = pos.get("atr", entry * 0.002)
        peak   = pos.get("peak", entry)
        t_open = pos.get("time", time.time())

        raw_pnl = (price-entry)/entry*amount if action=="BUY" else (entry-price)/entry*amount
        pnl_pct = raw_pnl / amount * 100

        with lock:
            for p in state["positions"]:
                if p["id"] == pos["id"]:
                    p["pnl"] = round(raw_pnl, 5)

        be       = pos.get("be_set", False)
        trail_on = pos.get("trail_on", False)

        # BREAKEVEN after 0.5% profit
        if not be and pnl_pct > 0.5:
            be_price = entry*(1+FEE_RATE*2.2) if action=="BUY" else entry*(1-FEE_RATE*2.2)
            if (action=="BUY" and be_price>sl) or (action=="SELL" and be_price<sl):
                with lock:
                    for p in state["positions"]:
                        if p["id"] == pos["id"]:
                            p["sl"] = round(be_price, 4); p["be_set"] = True
                sl = be_price; be = True

        # TRAILING: ATR × 1.5 distance, activates after 0.4% profit
        if not trail_on and pnl_pct > 0.4:
            with lock:
                for p in state["positions"]:
                    if p["id"] == pos["id"]:
                        p["trail_on"] = True
            trail_on = True

        if trail_on:
            trail_dist = atr * 1.5
            if action == "BUY" and price > peak:
                new_sl = price - trail_dist
                if new_sl > sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"] = round(new_sl, 4); p["peak"] = price
                    sl = new_sl; peak = price
            elif action == "SELL" and price < peak:
                new_sl = price + trail_dist
                if new_sl < sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"] = round(new_sl, 4); p["peak"] = price
                    sl = new_sl; peak = price

        # EXITS
        exit_reason = None; exit_pnl = 0.0

        if action=="BUY"  and price >= tp:
            exit_reason="TP"; exit_pnl=(tp-entry)/entry*amount - amount*FEE_RATE
        elif action=="SELL" and price <= tp:
            exit_reason="TP"; exit_pnl=(entry-tp)/entry*amount - amount*FEE_RATE
        elif action=="BUY"  and price <= sl:
            exit_reason="SL"; exit_pnl=(sl-entry)/entry*amount - amount*FEE_RATE
        elif action=="SELL" and price >= sl:
            exit_reason="SL"; exit_pnl=(entry-sl)/entry*amount - amount*FEE_RATE
        elif time.time()-t_open > MAX_TIME and raw_pnl > amount*FEE_RATE:
            exit_reason="TIME"; exit_pnl=raw_pnl - amount*FEE_RATE
        elif time.time()-t_open > 10800 and pnl_pct < -(pos["sl_pct"]*2.5):
            exit_reason="EMERGENCY"; exit_pnl=raw_pnl - amount*FEE_RATE

        if exit_reason:
            _close(pos, exit_reason, exit_pnl, price)


def _close(pos, reason, pnl, close_price):
    amount = pos["amount"]
    record = {
        "id": pos["id"], "pair": pos["pair"], "action": pos["action"],
        "entry": pos["entry"], "exit": close_price,
        "amount": round(amount, 5), "pnl": round(pnl, 5),
        "pnl_pct": round(pnl/amount*100, 3),
        "reason": reason, "mode": pos.get("mode",""),
        "confidence": pos.get("confidence",0), "reasons": pos.get("reasons",[]),
        "duration": round((time.time()-pos["time"])/60, 1),
        "time": pos.get("time_str",""),
        "exit_time": datetime.now().strftime("%H:%M:%S"),
        "won": pnl > 0,
    }
    emoji = "✅" if pnl > 0 else "❌"
    with lock:
        state["balance"] += amount + pnl
        if state["balance"] > state["peak_balance"]:
            state["peak_balance"] = state["balance"]
            # Don't count open position deductions as drawdown
        effective_balance = state["balance"] + sum(p["amount"] for p in state["positions"])
        dd = (state["peak_balance"]-effective_balance)/state["peak_balance"]*100
        dd = (state["peak_balance"]-state["balance"])/state["peak_balance"]*100
        if dd > state["max_drawdown"]: state["max_drawdown"] = round(dd, 2)
        if pnl > 0:
            state["winning_trades"] += 1; state["daily_wins"] += 1
        else:
            state["losing_trades"] += 1; state["daily_loss"] += abs(pnl)
        state["total_pnl"] = state["balance"] - state["initial_balance"]
        state["trades"].insert(0, record)
        if len(state["trades"]) > 200: state["trades"].pop()
        state["positions"] = [p for p in state["positions"] if p["id"] != pos["id"]]
        state["equity_curve"].append({"t": datetime.now().strftime("%H:%M"), "v": round(state["balance"], 5)})
        if len(state["equity_curve"]) > 300: state["equity_curve"].pop(1)
    print(f"{emoji} [{reason}] {pos['pair']} {pos['action']} @${close_price:.3f} PnL:${pnl:+.5f}({record['pnl_pct']:+.2f}%) {record['duration']}min")


def daily_reset():
    import datetime as dt
    h = dt.datetime.utcnow().hour
    with lock:
        if h == 0 and state.get("daily_reset_hour") != 0:
            state["daily_trades"] = 0; state["daily_loss"] = 0.0
            state["daily_wins"] = 0;   state["daily_reset_hour"] = 0
        elif h != 0:
            state["daily_reset_hour"] = h
