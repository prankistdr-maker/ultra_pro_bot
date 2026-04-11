"""
Trade Execution - PROFESSIONAL
Key principles:
- Risk only 1.5% of balance per trade
- SL minimum 0.5% (fees = 0.2% round trip, need breathing room)
- Never exit TIME when losing (let TP/SL do the job)
- Trailing only after 0.4% profit (don't trail into breakeven too early)
- Track every trade detail for analysis
- Max 4 trades per day, max 1 open position
"""
import time
from datetime import datetime
from app.state import state, lock

FEE_RATE  = 0.001    # 0.1% per side = 0.2% round trip
MIN_TRADE = 20       # Minimum $20 per trade
RISK_PCT  = 0.015    # Risk 1.5% of balance per trade
MAX_TIME  = 5400     # 60 minutes max (was 45, increased for better TP hits)


def execute(action, sl_pct, tp_pct, confidence, reasons, mode):
    """Open a new position with full risk management"""
    with lock:
        price     = state["price"]
        balance   = state["balance"]
        positions = state["positions"]

    # Safety checks
    if price <= 0 or balance < 50:
        return
    if len(positions) >= 1:
        return

    # ── POSITION SIZING (risk-based) ────────────────
    # We risk exactly RISK_PCT of balance
    # Position size = how much to trade so that SL loss = risk amount
    risk_amount = balance * RISK_PCT
    sl_dollar   = price * sl_pct / 100

    if sl_dollar > 0:
        units       = risk_amount / sl_dollar
        trade_value = units * price
    else:
        trade_value = risk_amount * 10  # Fallback

    # Caps: never more than 25% of balance in one trade
    trade_value = min(trade_value, balance * 0.25)
    trade_value = max(trade_value, MIN_TRADE)

    if trade_value > balance * 0.9:
        return

    # Entry fee
    entry_fee = trade_value * FEE_RATE

    # SL and TP prices
    if action == "BUY":
        sl_price = price * (1 - sl_pct / 100)
        tp_price = price * (1 + tp_pct / 100)
    else:
        sl_price = price * (1 + sl_pct / 100)
        tp_price = price * (1 - tp_pct / 100)

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
        "trail_activated": False,    # Only trail after 0.4% profit
        "breakeven_set":   False,    # Move SL to breakeven after 0.6%
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

    print(f"[TRADE] {action} @ ${price:,.2f} | "
          f"SL:{sl_pct:.1f}% (${sl_price:,.0f}) "
          f"TP:{tp_pct:.1f}% (${tp_price:,.0f}) | "
          f"Size:${trade_value:.0f} | Conf:{confidence}/10 | {mode}")


def manage_positions():
    """
    Called every 3 seconds.
    Professional position management:
    1. Track live PnL
    2. Move to breakeven after 0.6% profit (protect capital)
    3. Trail stop after 0.4% profit (lock profits)
    4. Exit on TP/SL
    5. TIME exit ONLY if profitable (never lock in a loss from time)
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

        # ── LIVE PNL ────────────────────────────────
        if action == "BUY":
            raw_pnl = (price - entry) / entry * amount
        else:
            raw_pnl = (entry - price) / entry * amount

        pnl_pct = raw_pnl / amount * 100

        # Update display PnL
        with lock:
            for p in state["positions"]:
                if p["id"] == pos["id"]:
                    p["pnl"] = round(raw_pnl, 2)

        trail_activated = pos.get("trail_activated", False)
        breakeven_set   = pos.get("breakeven_set", False)

        # ── BREAKEVEN (after 0.6% profit) ───────────
        # Move SL to entry+fee so worst case is breakeven
        if not breakeven_set and pnl_pct > 0.6:
            be_sl = entry * (1 + FEE_RATE * 2) if action == "BUY" else entry * (1 - FEE_RATE * 2)
            if (action == "BUY" and be_sl > sl) or (action == "SELL" and be_sl < sl):
                with lock:
                    for p in state["positions"]:
                        if p["id"] == pos["id"]:
                            p["sl"]           = round(be_sl, 2)
                            p["breakeven_set"] = True
                sl = be_sl
                breakeven_set = True
                print(f"[BREAKEVEN] {pos['id']} SL moved to ${be_sl:,.2f}")

        # ── TRAILING STOP (after 0.4% profit) ────────
        # Only starts trailing after we have real profit
        # Prevents being stopped out by noise
        if not trail_activated and pnl_pct > 0.4:
            with lock:
                for p in state["positions"]:
                    if p["id"] == pos["id"]:
                        p["trail_activated"] = True
            trail_activated = True

        if trail_activated:
            if action == "BUY" and price > peak:
                trail_dist = price * sl_pct / 100
                new_sl     = price - trail_dist
                if new_sl > sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"]   = round(new_sl, 2)
                                p["peak"] = price
                    sl   = new_sl
                    peak = price

            elif action == "SELL" and price < peak:
                trail_dist = price * sl_pct / 100
                new_sl     = price + trail_dist
                if new_sl < sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"]   = round(new_sl, 2)
                                p["peak"] = price
                    sl   = new_sl
                    peak = price

        # ── EXIT CONDITIONS ──────────────────────────
        exit_reason = None
        exit_pnl    = 0.0

        # Take Profit ✅
        if action == "BUY" and price >= tp:
            exit_reason = "TP"
            exit_pnl    = (tp - entry) / entry * amount - amount * FEE_RATE

        elif action == "SELL" and price <= tp:
            exit_reason = "TP"
            exit_pnl    = (entry - tp) / entry * amount - amount * FEE_RATE

        # Stop Loss ❌
        elif action == "BUY" and price <= sl:
            exit_reason = "SL"
            exit_pnl    = (sl - entry) / entry * amount - amount * FEE_RATE

        elif action == "SELL" and price >= sl:
            exit_reason = "SL"
            exit_pnl    = (entry - sl) / entry * amount - amount * FEE_RATE

        # Time Exit ⏱ — ONLY if profitable
        # KEY FIX: Never lock in losses from time — wait for TP or SL
        elif time.time() - time_open > MAX_TIME:
            if raw_pnl > (amount * FEE_RATE):  # Profitable after fees
                exit_reason = "TIME"
                exit_pnl    = raw_pnl - amount * FEE_RATE
            # else: let it run until TP or SL — don't force a loss

        if exit_reason:
            _close(pos, exit_reason, exit_pnl, price)


def _close(pos, reason, pnl, close_price):
    """Close position and record complete trade history"""
    amount = pos["amount"]

    record = {
        "id":         pos["id"],
        "action":     pos["action"],
        "entry":      pos["entry"],
        "exit":       close_price,
        "amount":     round(amount, 2),
        "pnl":        round(pnl, 4),
        "pnl_pct":    round(pnl / amount * 100, 2),
        "reason":     reason,
        "mode":       pos.get("mode", ""),
        "confidence": pos.get("confidence", 0),
        "reasons":    pos.get("reasons", []),
        "duration":   round((time.time() - pos["time"]) / 60, 1),
        "time":       pos.get("time_str", ""),
        "exit_time":  datetime.now().strftime("%H:%M:%S"),
        "won":        pnl > 0,
    }

    emoji = "✅" if pnl > 0 else "❌"

    with lock:
        # Return capital + pnl to balance
        state["balance"] += amount + pnl

        # Update peak for drawdown tracking
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

        # Full trade history
        state["trades"].insert(0, record)
        if len(state["trades"]) > 200:
            state["trades"].pop()

        # Remove from open positions
        state["positions"] = [
            p for p in state["positions"]
            if p["id"] != pos["id"]
        ]

    print(f"{emoji} [CLOSE] {pos['action']} {reason} @ ${close_price:,.2f} "
          f"| PnL: ${pnl:+.2f} ({record['pnl_pct']:+.1f}%) "
          f"| {record['duration']}min")


def daily_reset():
    """Reset daily counters at UTC midnight"""
    import datetime as dt
    hour = dt.datetime.utcnow().hour
    with lock:
        if hour == 0 and state.get("daily_reset_hour") != 0:
            state["daily_trades"]     = 0
            state["daily_loss"]       = 0.0
            state["daily_wins"]       = 0
            state["daily_reset_hour"] = 0
        elif hour != 0:
            state["daily_reset_hour"] = hour
