from app.state import state
import time

FEE = 0.001
MIN_TRADE = 10
RISK_PERCENT = 0.02


def execute(action):
    price = state["price"]

    # =========================
    # 🔒 SAFETY & LIMITS
    # =========================

    if price <= 0:
        return

    # max 2 open trades
    if len(state["positions"]) >= 2:
        return

    # cooldown (avoid spam trades)
    if time.time() - state["last_trade_time"] < 30:
        return

    # daily limits
    if state["daily_trades"] >= 40:
        return

    if state["daily_loss"] > state["balance"] * 0.1:
        return

    balance = state["balance"]

    trade_amount = max(MIN_TRADE, balance * RISK_PERCENT)

    if trade_amount > balance:
        trade_amount = balance

    # =========================
    # 🧠 MARKET MODE
    # =========================

    mode = state.get("market_mode", "NORMAL")

    # 🎯 DYNAMIC TP/SL (REALISTIC)
    if mode == "SCALP":
        tp = price * 1.003     # 0.3%
        sl = price * 0.997     # 0.3%

    elif mode == "TREND":
        tp = price * 1.01      # 1%
        sl = price * 0.995     # 0.5%

    else:  # NORMAL
        tp = price * 1.006     # 0.6%
        sl = price * 0.995

    # =========================
    # 🟢 EXECUTE BUY
    # =========================

    if action == "BUY" and balance >= MIN_TRADE:

        position = {
            "entry": price,
            "amount": trade_amount,
            "sl": sl,
            "tp": tp,
            "time": time.time()
        }

        state["positions"].append(position)
        state["balance"] -= trade_amount
        state["last_trade_time"] = time.time()
        state["daily_trades"] += 1

    # =========================
    # 🔄 MANAGE POSITIONS
    # =========================

    for pos in state["positions"][:]:

        entry = pos["entry"]
        amount = pos["amount"]

        # =====================
        # 📈 TRAILING STOP
        # =====================
        if price > entry * 1.002:
            pos["sl"] = max(pos["sl"], price * 0.998)

        # =====================
        # ⚡ QUICK SCALP EXIT
        # =====================
        if price > entry * 1.002:
            profit = amount * 0.002
            state["balance"] += amount + profit - profit * FEE
            state["trades"].append(profit)
            state["positions"].remove(pos)
            continue

        # =====================
        # 📉 EARLY EXIT (MARKET FLIP)
        # =====================
        if state["signals"].get("trend") == "bearish":
            state["balance"] += amount
            state["trades"].append(0)
            state["positions"].remove(pos)
            continue

        # =====================
        # ⏱️ TIME-BASED EXIT
        # =====================
        if time.time() - pos["time"] > 300:  # 5 min
            state["balance"] += amount
            state["trades"].append(0)
            state["positions"].remove(pos)
            continue

        # =====================
        # 🔴 STOP LOSS
        # =====================
        if price <= pos["sl"]:
            loss = amount * 0.003
            state["balance"] += amount - loss
            state["trades"].append(-loss)
            state["daily_loss"] += loss
            state["positions"].remove(pos)
            state["last_trade_time"] = time.time() + 60
            continue

        # =====================
        # 🟢 TAKE PROFIT
        # =====================
        if price >= pos["tp"]:
            profit = amount * 0.005
            state["balance"] += amount + profit - profit * FEE
            state["trades"].append(profit)
            state["positions"].remove(pos)
