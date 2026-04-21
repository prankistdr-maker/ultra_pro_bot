import time
from datetime import datetime
from app.state import state, lock

FEE = 0.001

def execute(pair, decision, ind, price):
    with lock:
        balance = state["balance"]
        positions = state["positions"]

    if price <= 0 or balance < 2:
        return False
    if [p for p in positions if p["pair"] == pair]:
        return False
    if len(positions) >= 3:
        return False

    action = decision["action"]
    sl_pct = decision["sl_pct"]
    tp1_pct = decision.get("tp1_pct", sl_pct*1.5)
    tp2_pct = decision.get("tp2_pct", sl_pct*3.0)
    risk_pct = decision["risk_pct"]
    leverage = decision.get("leverage", 5)

    # Position size with leverage
    risk_amt = balance * risk_pct / 100
    sl_dist = price * sl_pct / 100
    # Notional size = risk_amt / (sl_dist/price) * leverage? Actually we want the loss to equal risk_amt if SL hit.
    # With leverage, loss = (sl_dist/price) * notional. So notional = risk_amt / (sl_dist/price)
    notional = risk_amt / (sl_dist / price) if sl_dist > 0 else balance * 0.05
    # Margin required = notional / leverage
    margin = notional / leverage
    if margin > balance * 0.8:  # don't use more than 80% of balance as margin
        leverage = max(1, int(notional / (balance * 0.8)))
        margin = notional / leverage
    if margin > balance:
        return False

    # Amount in base currency (e.g., BTC amount)
    amount = notional / price

    sl_price = price*(1-sl_pct/100) if action=="BUY" else price*(1+sl_pct/100)
    tp1_price = price*(1+tp1_pct/100) if action=="BUY" else price*(1-tp1_pct/100)
    tp2_price = price*(1+tp2_pct/100) if action=="BUY" else price*(1-tp2_pct/100)
    liq_price = price*(1 - 0.9/leverage) if action=="BUY" else price*(1 + 0.9/leverage)  # rough est

    pos = {
        "id": f"{pair[:3]}{int(time.time())}",
        "pair": pair,
        "action": action,
        "entry": price,
        "amount": amount,
        "notional": notional,
        "leverage": leverage,
        "margin": margin,
        "sl": round(sl_price, 4),
        "tp1": round(tp1_price, 4),
        "tp2": round(tp2_price, 4),
        "liq": round(liq_price, 4),
        "tp1_hit": False,
        "partial_closed": False,
        "sl_pct": sl_pct,
        "tp_pct": tp2_pct,
        "atr": ind.get("atr", price*0.002),
        "peak": price,
        "trail_on": False,
        "be_set": False,
        "time": time.time(),
        "time_str": datetime.now().strftime("%H:%M:%S"),
        "reasoning": decision.get("reasoning", ""),
        "setup_type": decision.get("setup_type", ""),
        "confidence": decision.get("confidence", 5),
        "pnl": 0.0,
    }

    with lock:
        state["positions"].append(pos)
        state["balance"] -= margin  # lock margin
        state["margin_used"] += margin
        state["last_trade_time"][pair] = time.time()
        state["daily_trades"] += 1
        state["total_trades"] += 1
        state["current_leverage"][pair] = leverage

    print(f"[TRADE] {pair} {action} @${price:.4f} | Lev:{leverage}x | Margin:${margin:.2f} | SL:{sl_pct}% TP1:{tp1_pct}% TP2:{tp2_pct}%")
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
        entry = pos["entry"]
        amount = pos["amount"]
        notional = pos["notional"]
        leverage = pos["leverage"]
        margin = pos["margin"]
        sl = pos["sl"]
        tp1 = pos.get("tp1", entry)
        tp2 = pos.get("tp2", entry)
        liq = pos.get("liq", 0)
        atr = pos.get("atr", entry*0.002)
        peak = pos.get("peak", entry)
        t_open = pos.get("time", time.time())

        # PnL (unrealized) with leverage
        if action == "BUY":
            pnl_abs = (price - entry) / entry * notional
        else:
            pnl_abs = (entry - price) / entry * notional
        pnl_pct = (pnl_abs / margin) * 100 if margin > 0 else 0

        with lock:
            for p in state["positions"]:
                if p["id"] == pos["id"]:
                    p["pnl"] = round(pnl_abs, 5)

        # Liquidation check
        if (action == "BUY" and price <= liq) or (action == "SELL" and price >= liq):
            _close(pos, "LIQUIDATED", -margin, price)
            continue

        # Partial TP at TP1
        if not pos.get("tp1_hit", False):
            if (action == "BUY" and price >= tp1) or (action == "SELL" and price <= tp1):
                close_amt = amount * 0.5
                close_notional = notional * 0.5
                if action == "BUY":
                    close_pnl = (tp1 - entry) / entry * close_notional
                else:
                    close_pnl = (entry - tp1) / entry * close_notional
                close_pnl -= close_notional * FEE
                with lock:
                    state["balance"] += margin * 0.5 + close_pnl  # return half margin + profit
                    state["margin_used"] -= margin * 0.5
                    for p in state["positions"]:
                        if p["id"] == pos["id"]:
                            p["amount"] -= close_amt
                            p["notional"] -= close_notional
                            p["margin"] -= margin * 0.5
                            p["tp1_hit"] = True
                            p["partial_closed"] = True
                            p["sl"] = entry  # move to breakeven
                            p["be_set"] = True
                amount -= close_amt
                notional -= close_notional
                margin -= margin * 0.5
                sl = entry
                print(f"[PARTIAL TP] {pair} closed 50% at ${tp1:.4f} PnL:${close_pnl:+.5f}")
                continue

        # Breakeven if not already
        if not pos.get("be_set", False) and pnl_pct > 0.6 * leverage:
            be_p = entry * (1 + FEE * 2.2) if action == "BUY" else entry * (1 - FEE * 2.2)
            if (action == "BUY" and be_p > sl) or (action == "SELL" and be_p < sl):
                with lock:
                    for p in state["positions"]:
                        if p["id"] == pos["id"]:
                            p["sl"] = round(be_p, 4)
                            p["be_set"] = True
                sl = be_p

        # Trailing stop after 1.5x ATR profit (in % terms)
        trail_threshold = atr * 1.5 / entry * 100 * leverage
        if not pos.get("trail_on", False) and pnl_pct > trail_threshold:
            with lock:
                for p in state["positions"]:
                    if p["id"] == pos["id"]:
                        p["trail_on"] = True
        if pos.get("trail_on", False):
            trail_dist = atr * 1.2
            if action == "BUY" and price > peak:
                new_sl = price - trail_dist
                if new_sl > sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"] = round(new_sl, 4)
                                p["peak"] = price
                    sl = new_sl
            elif action == "SELL" and price < peak:
                new_sl = price + trail_dist
                if new_sl < sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"] = round(new_sl, 4)
                                p["peak"] = price
                    sl = new_sl

        # Emergency retrace exit
        max_profit_pct = ((peak - entry) / entry * 100 * leverage) if action == "BUY" else ((entry - peak) / entry * 100 * leverage)
        if max_profit_pct > 5.0 and pnl_pct < max_profit_pct * 0.3:
            _close(pos, "RETRACE", pnl_abs - notional * FEE, price)
            continue

        # TP2 / SL / Time exits
        er = None
        ep = 0.0
        if action == "BUY" and price >= tp2:
            er = "TP2"
            ep = (tp2 - entry) / entry * notional - notional * FEE
        elif action == "SELL" and price <= tp2:
            er = "TP2"
            ep = (entry - tp2) / entry * notional - notional * FEE
        elif action == "BUY" and price <= sl:
            er = "SL"
            ep = (sl - entry) / entry * notional - notional * FEE
        elif action == "SELL" and price >= sl:
            er = "SL"
            ep = (entry - sl) / entry * notional - notional * FEE
        elif time.time() - t_open > 14400:
            er = "TIME"
            ep = pnl_abs - notional * FEE

        if er:
            _close(pos, er, ep, price)


def _close(pos, reason, pnl, cp):
    margin = pos["margin"]
    amount = pos.get("notional", pos["amount"] * pos["entry"])
    with lock:
        # Return remaining margin + PnL
        state["balance"] += margin + pnl
        state["margin_used"] -= margin
        if state["balance"] > state["peak_balance"]:
            state["peak_balance"] = state["balance"]
        # Update stats
        if pnl > 0:
            state["winning_trades"] += 1
            state["daily_wins"] += 1
        else:
            state["losing_trades"] += 1
            state["daily_loss"] += abs(pnl)
        state["total_pnl"] = state["balance"] - state["initial_balance"]
        # Record trade
        rec = {
            "id": pos["id"], "pair": pos["pair"], "action": pos["action"],
            "entry": pos["entry"], "exit": cp, "amount": round(amount, 5),
            "pnl": round(pnl, 5), "pnl_pct": round(pnl / margin * 100, 2) if margin > 0 else 0,
            "reason": reason, "setup_type": pos.get("setup_type", ""),
            "reasoning": pos.get("reasoning", ""), "confidence": pos.get("confidence", 5),
            "leverage": pos.get("leverage", 1), "duration": round((time.time() - pos["time"]) / 60, 1),
            "time": pos.get("time_str", ""), "exit_time": datetime.now().strftime("%H:%M:%S"),
            "won": pnl > 0,
        }
        state["trades"].insert(0, rec)
        if len(state["trades"]) > 200:
            state["trades"].pop()
        state["positions"] = [p for p in state["positions"] if p["id"] != pos["id"]]
        state["equity_curve"].append({"t": datetime.now().strftime("%H:%M"), "v": round(state["balance"], 5)})
        if len(state["equity_curve"]) > 300:
            state["equity_curve"].pop(1)
    emoji = "✅" if pnl > 0 else "❌"
    print(f"{emoji} [{reason}] {pos['pair']} {pos['action']} @${cp:.4f} PnL:${pnl:+.5f} ({rec['pnl_pct']:+.1f}%) {rec['duration']}min")


def daily_reset():
    import datetime as dt
    h = dt.datetime.utcnow().hour
    with lock:
        if h == 0 and state.get("daily_reset_hour") != 0:
            state["daily_trades"] = 0
            state["daily_loss"] = 0.0
            state["daily_wins"] = 0
            state["daily_reset_hour"] = 0
        elif h != 0:
            state["daily_reset_hour"] = h
