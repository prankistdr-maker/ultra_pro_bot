from app.state import state
import time

FEE = 0.001
MIN_TRADE = 10
RISK_PERCENT = 0.02

def execute(action):
    price = state["price"]

    # ❌ Max 2 trades
    if len(state["positions"]) >= 2:
        return

    # ❌ Cooldown (1 min)
    if time.time() - state["last_trade_time"] < 60:
        return

    # ❌ Daily trade limit
    if state["daily_trades"] >= 20:
        return

    # ❌ Daily loss limit (10%)
    if state["daily_loss"] > state["balance"] * 0.1:
        return

    balance = state["balance"]
    trade_amount = max(MIN_TRADE, balance * RISK_PERCENT)

    if trade_amount > balance:
        trade_amount = balance

    # ✅ BUY
    if action == "BUY" and balance >= MIN_TRADE:

        sl = price * 0.98
        tp = price * 1.04

        position = {
            "entry": price,
            "amount": trade_amount,
            "sl": sl,
            "tp": tp
        }

        state["positions"].append(position)
        state["balance"] -= trade_amount
        state["last_trade_time"] = time.time()
        state["daily_trades"] += 1

    # 🔄 Manage trades
    for pos in state["positions"][:]:

        # TRAILING STOP
        if price > pos["entry"] * 1.02:
            pos["sl"] = pos["entry"]

        # STOP LOSS
        if price <= pos["sl"]:
            loss = pos["amount"]
            state["balance"] += pos["amount"] - loss * FEE
            state["trades"].append(-loss)
            state["daily_loss"] += loss
            state["positions"].remove(pos)
            state["last_trade_time"] = time.time() + 120

        # TAKE PROFIT
        elif price >= pos["tp"]:
            profit = pos["amount"] * 2
            state["balance"] += pos["amount"] + profit - profit * FEE
            state["trades"].append(profit)
            state["positions"].remove(pos)
