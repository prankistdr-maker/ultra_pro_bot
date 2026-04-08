def market_mode(signals):
    if signals["structure"] == "HH" and signals["trend"] == "bullish":
        return "TREND"

    if signals["structure"] == "range":
        return "SCALP"

    return "NORMAL"


def decide(signals):
    mode = market_mode(signals)

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

    # MODE BASED ENTRY
    if mode == "SCALP" and score >= 3:
        return "BUY", score, mode

    if mode == "TREND" and score >= 5:
        return "BUY", score, mode

    if mode == "NORMAL" and score >= 4:
        return "BUY", score, mode

    return "HOLD", score, mode
