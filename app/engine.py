def decide(signals):
    score = 0

    if signals["trend"] == "bullish":
        score += 2

    if signals["structure"] == "HH":
        score += 1

    if signals["liquidity"]:
        score += 2

    if signals["ob"]:
        score += 1

    if signals["fvg"]:
        score += 1

    if signals["rsi"] < 45:
        score += 1

    # ❌ Avoid sideways market
    if signals["structure"] == "range":
        return "HOLD", score

    # ❌ Avoid bearish setups
    if signals["trend"] == "bearish":
        return "HOLD", score

    if score >= 5:
        return "BUY", score

    return "HOLD", score
