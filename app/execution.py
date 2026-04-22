```python
"""
Execution - Dynamic Risk Scaling + Structure-Based SL/TP
As account grows: risk% drops but absolute dollar profit grows.
$20 account  → risk 20% ($4) → TP hit ~$0.90
$100 account → risk 10% ($10) → TP hit ~$2.30
$300 account → risk 5%  ($15) → TP hit ~$3.45
"""
import time
from datetime import datetime
from app.state import state, lock

FEE = 0.001


def get_dynamic_sizing(balance):
    """
    Dynamic risk scaling:
    Small account = higher risk% for meaningful profits
    Large account = lower risk% to protect capital
    But absolute dollar risk (and profit) keeps growing
    """
    if balance < 25:
        return 20.0, 10   # 20% risk, 10x max lev
    elif balance < 50:
        return 15.0, 8
    elif balance < 100:
        return 10.0, 6
    elif balance < 200:
        return 7.0, 5
    elif balance < 500:
        return 5.0, 4
    else:
        return 3.0, 3     # 3% risk, 3x max lev


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

    action = decision["action"]

    # Use exact price levels if provided (structure-based), otherwise fallback to percentages
    if "sl_price" in decision:
        sl_price = decision["sl_price"]
        tp1_price = decision.get("tp1_price", price * 1.01 if action == "BUY" else price * 0.99)
        tp2_price = decision.get("tp2_price", price * 1.02 if action == "BUY" else price * 0.98)
        # Calculate percentages for logging
        sl_pct = abs(price - sl_price) / price * 100
        tp2_pct = abs(tp2_price - price) / price * 100
    else:
        # Legacy percentage mode (kept for compatibility)
        sl_pct = decision["sl_pct"]
        tp2_pct = decision.get("tp2_pct", sl_pct * 3.0)
        sl_price = price * (1 - sl_pct / 100) if action == "BUY" else price * (1 + sl_pct / 100)
        tp2_price = price * (1 + tp2_pct / 100) if action == "BUY" else price * (1 - tp2_pct / 100)
        tp1_price = price * (1 + decision.get("tp1_pct", sl_pct * 1.5) / 100) if action == "BUY" else price * (1 - decision.get("tp1_pct", sl_pct * 1.5) / 100)

    # DYNAMIC SIZING — overrides Claude's suggestion
    risk_pct, max_lev = get_dynamic_sizing(balance)
    leverage = max(1, min(max_lev, int(decision.get("leverage", max_lev))))

    # Margin = what we actually put in
    margin = balance * risk_pct / 100
    if margin > balance * 0.95:
        margin = balance * 0.95

    # Notional = leveraged position size
    notional = margin * leverage

    liq_price = price * (1 - 0.85 / leverage) if action == "BUY" else price * (1 + 0.85 / leverage)

    # Expected profit/loss for display
    exp_profit = notional * tp2_pct / 100 - notional * FEE if 'tp2_pct' in locals() else notional * abs(tp2_price - price) / price - notional * FEE
    exp_loss   = notional * sl_pct / 100 + notional * FEE if 'sl_pct' in locals() else notional * abs(price - sl_price) / price + notional * FEE

    pos = {
        "id":             f"{pair[:3]}{int(time.time())}",
        "pair":           pair,
        "action":         action,
        "entry":          price,
        "amount":         notional / price,
        "notional":       notional,
        "leverage":       leverage,
        "margin":         margin,
        "sl":             round(sl_price, 4),
        "tp1":            round(tp1_price, 4),
        "tp2":            round(tp2_price, 4),
        "liq":            round(liq_price, 4),
        "tp1_hit":        False,
        "partial_closed": False,
        "sl_pct":         round(sl_pct, 3) if 'sl_pct' in locals() else 0.0,
        "tp_pct":         round(tp2_pct, 3) if 'tp2_pct' in locals() else 0.0,
        "atr":            ind.get("atr", price * 0.002),
        "peak":           price,
        "trail_on":       False,
        "be_set":         False,
        "time":           time.time(),
        "time_str":       datetime.now().strftime("%H:%M:%S"),
        "reasoning":      decision.get("reasoning", ""),
        "setup_type":     decision.get("setup_type", ""),
        "confidence":     decision.get("confidence", 5),
        "pnl":            0.0,
        "exp_profit":     round(exp_profit, 4),
        "exp_loss":       round(exp_loss, 4),
    }

    with lock:
        state["positions"].append(pos)
        state["balance"]              -= margin
        state["margin_used"]          += margin
        state["last_trade_time"][pair] = time.time()
        state["daily_trades"]         += 1
        state["total_trades"]         += 1
        state["current_leverage"][pair] = leverage

    rr = round(tp2_pct / sl_pct, 1) if 'sl_pct' in locals() and sl_pct > 0 else 0.0
    print(f"[TRADE] {pair} {action} @${price:.4f} | {leverage}x | "
          f"Margin:${margin:.3f} ({risk_pct:.0f}%) | Notional:${notional:.2f} | "
          f"SL:${sl_price:.4f} TP2:${tp2_price:.4f} R:R={rr} | "
          f"Est: +${exp_profit:.3f} / -${exp_loss:.3f}")
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

        action   = pos["action"]
        entry    = pos["entry"]
        notional = pos["notional"]
        leverage = pos["leverage"]
        margin   = pos["margin"]
        sl       = pos["sl"]
        tp1      = pos.get("tp1", entry)
        tp2      = pos.get("tp2", entry)
        liq      = pos.get("liq", 0)
        atr      = pos.get("atr", entry * 0.002)
        peak     = pos.get("peak", entry)
        t_open   = pos.get("time", time.time())

        if action == "BUY":
            pnl_abs = (price - entry) / entry * notional
        else:
            pnl_abs = (entry - price) / entry * notional
        pnl_pct = (pnl_abs / margin) * 100 if margin > 0 else 0

        with lock:
            for p in state["positions"]:
                if p["id"] == pos["id"]:
                    p["pnl"] = round(pnl_abs, 5)

        # Liquidation
        if (action == "BUY" and price <= liq) or (action == "SELL" and price >= liq):
            _close(pos, "LIQUIDATED", -margin, price)
            continue

        # Partial TP at TP1
        if not pos.get("tp1_hit", False):
            if (action == "BUY" and price >= tp1) or (action == "SELL" and price <= tp1):
                c_notional = notional * 0.5
                c_pnl = ((tp1 - entry) / entry * c_notional if action == "BUY"
                         else (entry - tp1) / entry * c_notional)
                c_pnl -= c_notional * FEE
                half_margin = margin * 0.5
                with lock:
                    state["balance"]     += half_margin + c_pnl
                    state["margin_used"] = max(0, state["margin_used"] - half_margin)
                    for p in state["positions"]:
                        if p["id"] == pos["id"]:
                            p["notional"]      -= c_notional
                            p["margin"]        -= half_margin
                            p["tp1_hit"]        = True
                            p["partial_closed"] = True
                            p["sl"]             = entry
                            p["be_set"]         = True
                notional -= c_notional
                margin   -= half_margin
                sl        = entry
                print(f"[PARTIAL TP1] {pair} 50% @${tp1:.4f} +${c_pnl:.4f}")
                continue

        # Breakeven after leverage-adjusted profit
        if not pos.get("be_set", False) and pnl_pct > 0.5 * leverage:
            be_p = entry * (1 + FEE * 2.2) if action == "BUY" else entry * (1 - FEE * 2.2)
            if (action == "BUY" and be_p > sl) or (action == "SELL" and be_p < sl):
                with lock:
                    for p in state["positions"]:
                        if p["id"] == pos["id"]:
                            p["sl"] = round(be_p, 4)
                            p["be_set"] = True
                sl = be_p

        # Trailing stop
        if not pos.get("trail_on", False) and pnl_pct > atr / entry * 100 * leverage * 1.5:
            with lock:
                for p in state["positions"]:
                    if p["id"] == pos["id"]:
                        p["trail_on"] = True

        if pos.get("trail_on", False):
            td = atr * 1.2
            if action == "BUY" and price > peak:
                ns = price - td
                if ns > sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"] = round(ns, 4)
                                p["peak"] = price
                    sl = ns
                    peak = price
            elif action == "SELL" and price < peak:
                ns = price + td
                if ns < sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"] = round(ns, 4)
                                p["peak"] = price
                    sl = ns
                    peak = price

        # Retrace exit — only if profit was big (10%+ on margin) and gave back 70%
        max_pnl_pct = ((peak - entry) / entry * 100 * leverage if action == "BUY"
                       else (entry - peak) / entry * 100 * leverage)
        if max_pnl_pct > 10.0 and pnl_pct < max_pnl_pct * 0.3:
            _close(pos, "RETRACE", pnl_abs - notional * FEE, price)
            continue

        # Main exits
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
    margin   = pos["margin"]
    notional = pos.get("notional", pos["amount"] * pos["entry"])
    rec = {
        "id":         pos["id"],
        "pair":       pos["pair"],
        "action":     pos["action"],
        "entry":      pos["entry"],
        "exit":       cp,
        "amount":     round(notional, 5),
        "pnl":        round(pnl, 5),
        "pnl_pct":    round(pnl / margin * 100, 2) if margin > 0 else 0,
        "reason":     reason,
        "setup_type": pos.get("setup_type", ""),
        "reasoning":  pos.get("reasoning", ""),
        "confidence": pos.get("confidence", 5),
        "leverage":   pos.get("leverage", 1),
        "margin":     round(margin, 4),
        "duration":   round((time.time() - pos["time"]) / 60, 1),
        "time":       pos.get("time_str", ""),
        "exit_time":  datetime.now().strftime("%H:%M:%S"),
        "won":        pnl > 0,
    }
    with lock:
        state["balance"] += margin + pnl
        state["margin_used"] = max(0, state["margin_used"] - margin)

        if state["balance"] > state["peak_balance"]:
            state["peak_balance"] = state["balance"]
        open_margin = sum(p["margin"] for p in state["positions"]
                         if p["id"] != pos["id"])
        eff = state["balance"] + open_margin
        dd  = max(0, (state["peak_balance"] - eff) / state["peak_balance"] * 100)
        if dd > state["max_drawdown"]:
            state["max_drawdown"] = round(dd, 2)

        if pnl > 0:
            state["winning_trades"] += 1
            state["daily_wins"] += 1
        else:
            state["losing_trades"] += 1
            state["daily_loss"] += abs(pnl)

        state["total_pnl"] = state["balance"] - state["initial_balance"]
        state["trades"].insert(0, rec)
        if len(state["trades"]) > 200:
            state["trades"].pop()
        state["positions"] = [p for p in state["positions"] if p["id"] != pos["id"]]
        state["equity_curve"].append({
            "t": datetime.now().strftime("%H:%M"),
            "v": round(state["balance"], 5)
        })
        if len(state["equity_curve"]) > 300:
            state["equity_curve"].pop(1)

    emoji = "✅" if pnl > 0 else "❌"
    print(f"{emoji} [{reason}] {pos['pair']} {pos['action']} @${cp:.4f} "
          f"PnL:${pnl:+.5f} ({rec['pnl_pct']:+.1f}%) {rec['duration']}min lev:{pos.get('leverage',1)}x")


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
```
