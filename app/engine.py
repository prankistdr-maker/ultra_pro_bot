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

    if signals["rsi"] < 40:
        score += 1

    # 🔥 LOWER threshold (important)
    if score >= 4:
        return "BUY", score

    return "HOLD", score