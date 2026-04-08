def market_structure(prices):
    if len(prices) < 5:
        return "neutral"

    if prices[-1] > prices[-2] > prices[-3]:
        return "HH"
    elif prices[-1] < prices[-2] < prices[-3]:
        return "LL"
    return "range"

def liquidity_sweep(prices):
    if len(prices) < 20:
        return False
    return prices[-1] > max(prices[-20:-1])

def order_block(prices):
    if len(prices) < 10:
        return False
    return abs(prices[-1] - prices[-5]) < 0.002 * prices[-1]

def fvg(prices):
    if len(prices) < 3:
        return False
    return abs(prices[-1] - prices[-3]) > 0.003 * prices[-1]