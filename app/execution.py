"""
Trade Execution Engine
- Proper position sizing
- Adaptive TP/SL based on ATR
- Trailing stop that actually trails
- Complete trade history with all details
- Daily limits and risk controls
"""
import time
from datetime import datetime
from app.state import state, lock

FEE_RATE    = 0.001   # 0.1% per side
MIN_BALANCE = 50      # Stop trading below this
RISK_PCT    = 0.02    # Risk 2% of balance per trade


def execute(action, sl_pct, tp_pct, confidence, reasons, mode):
    """Execute a trade with full risk management"""

    with lock:
        price   = state["price"]
        balance = state["balance"]

    if price <= 0 or balance < MIN_BALANCE:
        return

    # ─── POSITION SIZE (risk-based) ───────────────────
    # Risk exactly RISK_PCT of balance on this trade
    risk_amount  = balance * RISK_PCT
    sl_distance  = price * sl_pct / 100
    position_size = risk_amount / sl_distance if sl_distance > 0 else risk_amount / price

    # Trade value = how much capital we deploy
    trade_value = position_size * price
    trade_value = min(trade_value, balance * 0.3)  # Max 30% of balance per trade
    trade_value = max(trade_value, 10)              # Min $10

    if trade_value > balance:
        return

    sl_price = price * (1 - sl_pct / 100) if action == "BUY" else price * (1 + sl_pct / 100)
    tp_price = price * (1 + tp_pct / 100) if action == "BUY" else price * (1 - tp_pct / 100)

    position = {
        "id":           f"T{int(time.time())}",
        "action":       action,
        "entry":        price,
        "amount":       trade_value,
        "sl":           sl_price,
        "tp":           tp_price,
        "sl_pct":       round(sl_pct, 2),
        "tp_pct":       round(tp_pct, 2),
        "peak":         price,       # For trailing stop
        "trailing":     True,
        "time":         time.time(),
        "time_str":     datetime.now().strftime("%H:%M:%S"),
        "confidence":   confidence,
        "mode":         mode,
        "reasons":      reasons[:3], # Store top 3 reasons
        "status":       "OPEN",
        "fee_paid":     trade_value * FEE_RATE,
        "pnl":          0.0
    }

    with lock:
        state["positions"].append(position)
        state["balance"]         -= trade_value + trade_value * FEE_RATE
        state["last_trade_time"]  = time.time()
        state["daily_trades"]    += 1
        state["total_trades"]    += 1

    print(f"[TRADE] {action} @ ${price:,.2f} | SL:{sl_pct:.1f}% TP:{tp_pct:.1f}% | Conf:{confidence}/10 | Mode:{mode}")


def manage_positions():
    """
    Called every 2 seconds
    - Trailing stop management
    - Check TP/SL hits
    - Time-based exits
    - Market flip exits
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
        peak      = pos.get("peak", entry)
        sl_pct    = pos.get("sl_pct", 0.5)
        time_open = pos.get("time", time.time())

        # ─── LIVE PNL ──────────────────────────────
        if action == "BUY":
            raw_pnl = (price - entry) / entry * amount
        else:
            raw_pnl = (entry - price) / entry * amount

        # ─── TRAILING STOP ─────────────────────────
        if pos.get("trailing", True):
            if action == "BUY" and price > peak:
                # Move SL up to lock profits
                new_peak = price
                trail_dist = price * sl_pct / 100
                new_sl = price - trail_dist
                if new_sl > sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"]   = new_sl
                                p["peak"] = new_peak
                                p["pnl"]  = raw_pnl
                    sl = new_sl

            elif action == "SELL" and price < peak:
                new_peak = price
                trail_dist = price * sl_pct / 100
                new_sl = price + trail_dist
                if new_sl < sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"]   = new_sl
                                p["peak"] = new_peak
                                p["pnl"]  = raw_pnl
                    sl = new_sl

        # ─── CHECK EXIT CONDITIONS ─────────────────
        exit_reason = None
        exit_pnl    = 0

        # Take Profit
        if action == "BUY"  and price >= tp:
            exit_reason = "TP"
            profit = amount * pos["tp_pct"] / 100
            exit_pnl = profit - amount * FEE_RATE

        elif action == "SELL" and price <= tp:
            exit_reason = "TP"
            profit = amount * pos["tp_pct"] / 100
            exit_pnl = profit - amount * FEE_RATE

        # Stop Loss
        elif action == "BUY"  and price <= sl:
            exit_reason = "SL"
            loss = amount * (entry - sl) / entry
            exit_pnl = -loss - amount * FEE_RATE

        elif action == "SELL" and price >= sl:
            exit_reason = "SL"
            loss = amount * (sl - entry) / entry
            exit_pnl = -loss - amount * FEE_RATE

        # Time exit (max 30 minutes open)
        elif time.time() - time_open > 1800:
            exit_reason = "TIME"
            exit_pnl = raw_pnl - amount * FEE_RATE

        # Execute exit
        if exit_reason:
            _close_position(pos, exit_reason, exit_pnl, price)


def _close_position(pos, reason, pnl, close_price):
    """Close a position and record the trade"""
    amount = pos["amount"]

    trade_record = {
        "id":         pos["id"],
        "action":     pos["action"],
        "entry":      pos["entry"],
        "exit":       close_price,
        "amount":     amount,
        "pnl":        round(pnl, 4),
        "pnl_pct":    round(pnl / amount * 100, 2),
        "reason":     reason,
        "mode":       pos.get("mode", "NORMAL"),
        "confidence": pos.get("confidence", 0),
        "reasons":    pos.get("reasons", []),
        "duration":   round((time.time() - pos["time"]) / 60, 1),
        "time":       pos.get("time_str", ""),
        "exit_time":  datetime.now().strftime("%H:%M:%S"),
        "won":        pnl > 0
    }

    with lock:
        # Return capital
        state["balance"] += amount + pnl

        # Update peak balance for drawdown
        if state["balance"] > state["peak_balance"]:
            state["peak_balance"] = state["balance"]

        dd = (state["peak_balance"] - state["balance"]) / state["peak_balance"] * 100
        if dd > state["max_drawdown"]:
            state["max_drawdown"] = round(dd, 2)

        # Update stats
        if pnl > 0:
            state["winning_trades"] += 1
            state["daily_wins"]     += 1
        else:
            state["losing_trades"] += 1
            state["daily_loss"]    += abs(pnl)

        state["total_pnl"] = state["balance"] - state["initial_balance"]

        # Save trade record — FIXED trade history
        state["trades"].insert(0, trade_record)
        if len(state["trades"]) > 100:
            state["trades"].pop()

        # Remove from positions
        state["positions"] = [
            p for p in state["positions"] if p["id"] != pos["id"]
        ]

    print(f"[CLOSE] {pos['action']} {reason} @ ${close_price:,.2f} | PnL: ${pnl:+.2f} ({trade_record['pnl_pct']:+.1f}%)")


FEE_RATE = 0.001


def daily_reset():
    """Reset daily counters at midnight UTC"""
    import datetime as dt
    current_hour = dt.datetime.utcnow().hour
    with lock:
        if current_hour == 0 and state["daily_reset_hour"] != 0:
            state["daily_trades"]    = 0
            state["daily_loss"]      = 0.0
            state["daily_wins"]      = 0
            state["daily_reset_hour"] = 0
        elif current_hour != 0:
            state["daily_reset_hour"] = current_hour
