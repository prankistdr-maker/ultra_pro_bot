from app.state import state

FEE = 0.001
MIN_TRADE = 10      # ✅ minimum trade size
RISK_PERCENT = 0.02 # 2% risk

def execute(action):
    price = state["price"]

    # Limit max open trades
    if len(state["positions"]) >= 2:
        return

    # Decide trade size
    balance = state["balance"]

    trade_amount = max(MIN_TRADE, balance * RISK_PERCENT)

    # Don't exceed balance
    if trade_amount > balance:
        trade_amount = balance

    # BUY logic
    if action == "BUY" and balance >= MIN_TRADE:

        sl = price * 0.98   # 2% SL
        tp = price * 1.04   # 4% TP

        position = {
            "entry": price,
            "amount": trade_amount,
            "sl": sl,
            "tp": tp
        }

        state["positions"].append(position)
        state["balance"] -= trade_amount

    # Manage open trades
    for pos in state["positions"][:]:

        # STOP LOSS
        if price <= pos["sl"]:
            loss = pos["amount"]
            state["balance"] += pos["amount"] - loss * FEE
            state["trades"].append(-loss)
            state["positions"].remove(pos)

        # TAKE PROFIT
        elif price >= pos["tp"]:
            profit = pos["amount"] * 2   # RR = 2:1
            state["balance"] += pos["amount"] + profit - profit * FEE
            state["trades"].append(profit)
            state["positions"].remove(pos)