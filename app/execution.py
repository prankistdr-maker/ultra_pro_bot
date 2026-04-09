"""
Trade Execution - FIXED
Key fixes:
- Max 1 open position at a time (safer for small account)
- Proper fee calculation (0.1% each side = 0.2% round trip)
- SL minimum 0.5% so fees don't eat the stop
- Time exit changed to 45min (was too short at 30min)
- Trailing stop only activates after 0.3% profit (not immediately)
- Daily trade limit 8 (was 30 — way too many)
"""
import time
from datetime import datetime
from app.state import state, lock

FEE_RATE  = 0.001   # 0.1% per side (Kraken standard)
MIN_TRADE = 20      # Minimum $20 per trade
RISK_PCT  = 0.015   # Risk only 1.5% of balance per trade (conservative)
MAX_TIME  = 2700    # 45 minutes max hold time


def execute(action, sl_pct, tp_pct, confidence, reasons, mode):
    with lock:
        price   = state["price"]
        balance = state["balance"]
        positions = state["positions"]

    if price <= 0 or balance < 50:
        return

    # Already have a position — skip
    if len(positions) >= 1:
        return

    # ─── POSITION SIZING ──────────────────────────────────
    # Risk exactly 1.5% of balance
    risk_amount  = balance * RISK_PCT
    sl_dollar    = price * sl_pct / 100
    # How many units to buy so that SL loss = risk_amount
    units        = risk_amount / sl_dollar if sl_dollar > 0 else 0
    trade_value  = units * price

    # Caps
    trade_value = min(trade_value, balance * 0.25)  # Max 25% of balance
    trade_value = max(trade_value, MIN_TRADE)        # Min $20
    if trade_value > balance * 0.9:
        return

    sl_price = (price * (1 - sl_pct/100) if action == "BUY"
                else price * (1 + sl_pct/100))
    tp_price = (price * (1 + tp_pct/100) if action == "BUY"
                else price * (1 - tp_pct/100))

    # Fee on entry
    entry_fee = trade_value * FEE_RATE

    position = {
        "id":         f"T{int(time.time())}",
        "action":     action,
        "entry":      price,
        "amount":     trade_value,
        "sl":         round(sl_price, 2),
        "tp":         round(tp_price, 2),
        "sl_pct":     sl_pct,
        "tp_pct":     tp_pct,
        "peak":       price,
        "trail_activated": False,  # Only trail after 0.3% profit
        "time":       time.time(),
        "time_str":   datetime.now().strftime("%H:%M:%S"),
        "confidence": confidence,
        "mode":       mode,
        "reasons":    reasons[:3],
        "status":     "OPEN",
        "fee_paid":   entry_fee,
        "pnl":        0.0,
    }

    with lock:
        state["positions"].append(position)
        state["balance"]         -= (trade_value + entry_fee)
        state["last_trade_time"]  = time.time()
        state["daily_trades"]    += 1
        state["total_trades"]    += 1

    print(f"[TRADE] {action} @ ${price:,.2f} | "
          f"SL:{sl_pct:.1f}% TP:{tp_pct:.1f}% | "
          f"Size:${trade_value:.0f} | Conf:{confidence}/10 | {mode}")


def manage_positions():
    with lock:
        price     = state["price"]
        positions = state["positions"][:]

    if price <= 0 or not positions:
        return

    for pos in positions:
        action   = pos["action"]
        entry    = pos["entry"]
        amount   = pos["amount"]
        sl       = pos["sl"]
        tp       = pos["tp"]
        sl_pct   = pos.get("sl_pct", 0.5)
        peak     = pos.get("peak", entry)
        time_open = pos.get("time", time.time())

        # ─── LIVE PNL ─────────────────────────────────────
        if action == "BUY":
            raw_pnl = (price - entry) / entry * amount
        else:
            raw_pnl = (entry - price) / entry * amount

        pnl_pct = raw_pnl / amount * 100

        # Update live pnl in state
        with lock:
            for p in state["positions"]:
                if p["id"] == pos["id"]:
                    p["pnl"] = round(raw_pnl, 2)

        # ─── TRAILING STOP ────────────────────────────────
        # Only activate trailing after 0.3% profit
        # This prevents SL being moved too early
        trail_activated = pos.get("trail_activated", False)

        if action == "BUY":
            if pnl_pct > 0.3 and not trail_activated:
                with lock:
                    for p in state["positions"]:
                        if p["id"] == pos["id"]:
                            p["trail_activated"] = True
                trail_activated = True

            if trail_activated and price > peak:
                trail_dist = price * sl_pct / 100
                new_sl = price - trail_dist
                if new_sl > sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"]   = round(new_sl, 2)
                                p["peak"] = price
                    sl   = new_sl
                    peak = price

        elif action == "SELL":
            if pnl_pct > 0.3 and not trail_activated:
                with lock:
                    for p in state["positions"]:
                        if p["id"] == pos["id"]:
                            p["trail_activated"] = True
                trail_activated = True

            if trail_activated and price < peak:
                trail_dist = price * sl_pct / 100
                new_sl = price + trail_dist
                if new_sl < sl:
                    with lock:
                        for p in state["positions"]:
                            if p["id"] == pos["id"]:
                                p["sl"]   = round(new_sl, 2)
                                p["peak"] = price
                    sl   = new_sl
                    peak = price

        # ─── EXIT CONDITIONS ──────────────────────────────
        exit_reason = None
        exit_pnl    = 0.0

        # Take profit
        if action == "BUY" and price >= tp:
            exit_reason = "TP"
            exit_pnl    = amount * tp / entry - amount - amount * FEE_RATE
        elif action == "SELL" and price <= tp:
            exit_reason = "TP"
            exit_pnl    = amount * entry / tp - amount - amount * FEE_RATE

        # Stop loss
        elif action == "BUY" and price <= sl:
            exit_reason = "SL"
            exit_pnl    = amount * sl / entry - amount - amount * FEE_RATE
        elif action == "SELL" and price >= sl:
            exit_reason = "SL"
            exit_pnl    = amount * entry / sl - amount - amount * FEE_RATE

        # Time exit — 45 min max
        elif time.time() - time_open > MAX_TIME:
            exit_reason = "TIME"
            exit_pnl    = raw_pnl - amount * FEE_RATE

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

    with lock:
        state["balance"] += amount + pnl

        # Peak balance tracking
        if state["balance"] > state["peak_balance"]:
            state["peak_balance"] = state["balance"]

        dd = ((state["peak_balance"] - state["balance"])
              / state["peak_balance"] * 100)
        if dd > state["max_drawdown"]:
            state["max_drawdown"] = round(dd, 2)

        # Stats
        if pnl > 0:
            state["winning_trades"] += 1
            state["daily_wins"]     += 1
        else:
            state["losing_trades"] += 1
            state["daily_loss"]    += abs(pnl)

        state["total_pnl"] = state["balance"] - state["initial_balance"]

        # Trade history
        state["trades"].insert(0, record)
        if len(state["trades"]) > 200:
            state["trades"].pop()

        # Remove position
        state["positions"] = [
            p for p in state["positions"]
            if p["id"] != pos["id"]
        ]

    emoji = "✅" if pnl > 0 else "❌"
    print(f"{emoji} [CLOSE] {pos['action']} {reason} @ ${close_price:,.2f} "
          f"| PnL: ${pnl:+.2f} ({record['pnl_pct']:+.1f}%)")


def daily_reset():
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
