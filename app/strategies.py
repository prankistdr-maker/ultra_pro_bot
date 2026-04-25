"""
STRATEGY EVOLUTION ENGINE
===========================
8 different strategies run simultaneously (paper tracked).
Every 2 hours: score each strategy → kill bottom 2 → mutate top 2 → spawn 2 new.
Winner strategy gets real trades.

Strategies are defined by their ENTRY CONDITIONS + SL/TP math.
The engine finds which combination works best for current market.
"""

STRATEGY_POOL = {
    "S1_LIQ_CHOCH": {
        "name": "Liquidity + CHoCH",
        "description": "Waits for liquidity sweep then CHoCH confirmation",
        "entry_bull": lambda i5,i1: (i5["liq_sweep_bull"] and i5["choch_bull"]),
        "entry_bear": lambda i5,i1: (i5["liq_sweep_bear"] and i5["choch_bear"]),
        "sl_mult": 1.5, "tp_mult": 3.5, "min_conf": 7,
        "session_filter": True,  # London/NY only
        "htf_required": True,    # must align with 1H
    },
    "S2_FVG_FILL": {
        "name": "FVG Fill",
        "description": "Enters when price fills a Fair Value Gap",
        "entry_bull": lambda i5,i1: i5["fvg_bull"] and i5["ema_bull"],
        "entry_bear": lambda i5,i1: i5["fvg_bear"] and not i5["ema_bull"],
        "sl_mult": 1.2, "tp_mult": 2.5, "min_conf": 6,
        "session_filter": True,
        "htf_required": True,
    },
    "S3_OB_RETEST": {
        "name": "Order Block Retest",
        "description": "Enters on OB retest with volume confirmation",
        "entry_bull": lambda i5,i1: i5["ob_bull"] and i5["high_volume"],
        "entry_bear": lambda i5,i1: i5["ob_bear"] and i5["high_volume"],
        "sl_mult": 1.3, "tp_mult": 3.0, "min_conf": 6,
        "session_filter": True,
        "htf_required": True,
    },
    "S4_TREND_FOLLOW": {
        "name": "Trend Following",
        "description": "Rides confirmed trends with EMA alignment",
        "entry_bull": lambda i5,i1: (i5["trend"]=="STRONG_BULL" and i5["ema_strong_bull"]
                                      and i5["above_vwap"] and i5["rsi"]<65),
        "entry_bear": lambda i5,i1: (i5["trend"]=="BEAR" and not i5["ema_bull"]
                                      and not i5["above_vwap"] and i5["rsi"]>35),
        "sl_mult": 2.0, "tp_mult": 4.0, "min_conf": 7,
        "session_filter": False,  # trade in any session
        "htf_required": True,
    },
    "S5_RSI_EXTREME": {
        "name": "RSI Extreme + Structure",
        "description": "Mean reversion at RSI extremes near key levels",
        "entry_bull": lambda i5,i1: i5["rsi"]<32 and i5["pd_zone"]=="discount",
        "entry_bear": lambda i5,i1: i5["rsi"]>68 and i5["pd_zone"]=="premium",
        "sl_mult": 1.5, "tp_mult": 2.5, "min_conf": 6,
        "session_filter": True,
        "htf_required": False,   # contrarian, can ignore HTF
    },
    "S6_MULTI_SIGNAL": {
        "name": "Multi-Signal Confluence",
        "description": "Requires 3+ signals agreeing",
        "entry_bull": lambda i5,i1: sum([i5["liq_sweep_bull"],i5["choch_bull"],
                                          i5["fvg_bull"],i5["ob_bull"],
                                          i5["ema_bull"],i5["above_vwap"]])>=3,
        "entry_bear": lambda i5,i1: sum([i5["liq_sweep_bear"],i5["choch_bear"],
                                          i5["fvg_bear"],i5["ob_bear"],
                                          not i5["ema_bull"],not i5["above_vwap"]])>=3,
        "sl_mult": 1.4, "tp_mult": 3.0, "min_conf": 7,
        "session_filter": True,
        "htf_required": True,
    },
    "S7_BREAKOUT": {
        "name": "Structure Breakout",
        "description": "Trades breakouts of swing highs/lows with volume",
        "entry_bull": lambda i5,i1: (i5["hh"] and i5["hl"] and i5["high_volume"]
                                      and i5["rsi"]<70),
        "entry_bear": lambda i5,i1: (i5["ll"] and i5["lh"] and i5["high_volume"]
                                      and i5["rsi"]>30),
        "sl_mult": 1.6, "tp_mult": 3.5, "min_conf": 6,
        "session_filter": True,
        "htf_required": True,
    },
    "S8_BB_SQUEEZE": {
        "name": "Bollinger Band Squeeze",
        "description": "Trades BB extremes with trend confirmation",
        "entry_bull": lambda i5,i1: (i5["price"]<i5["bb_lower"] and i5["ema_bull"]
                                      and i5["rsi"]<45),
        "entry_bear": lambda i5,i1: (i5["price"]>i5["bb_upper"] and not i5["ema_bull"]
                                      and i5["rsi"]>55),
        "sl_mult": 1.3, "tp_mult": 2.8, "min_conf": 6,
        "session_filter": True,
        "htf_required": False,
    },
}


def init_strategy_stats():
    """Initialize tracking stats for all strategies"""
    stats = {}
    for sid, s in STRATEGY_POOL.items():
        stats[sid] = {
            "name":        s["name"],
            "trades":      0,
            "wins":        0,
            "losses":      0,
            "total_pnl":   0.0,
            "win_rate":    0.0,
            "expectancy":  0.0,  # (win_rate * avg_win) - (loss_rate * avg_loss)
            "avg_win":     0.0,
            "avg_loss":    0.0,
            "score":       50.0,  # starts neutral
            "active":      True,
            "generation":  1,
        }
    return stats


def score_strategy(stats):
    """
    Score a strategy based on performance.
    Expectancy = the most important metric.
    """
    if stats["trades"] < 3:
        return 50.0  # Not enough data yet

    wr  = stats["wins"] / stats["trades"]
    lr  = 1 - wr
    aw  = stats["avg_win"]
    al  = abs(stats["avg_loss"]) if stats["avg_loss"] < 0 else stats["avg_loss"]

    # Expectancy: positive = profitable strategy
    expectancy = (wr * aw) - (lr * al) if al > 0 else wr * aw

    # Score: 0-100, 50 = breakeven
    score = 50 + (expectancy * 500)   # scale to 0-100 range
    score = max(0, min(100, score))
    return round(score, 1)


def evaluate_and_evolve(strategy_stats, generation):
    """
    Every evaluation cycle:
    1. Score all strategies
    2. Kill bottom 2 (replace with mutations of top 2)
    3. Log the evolution
    Returns updated stats and evolution log entry
    """
    # Score all with enough data
    scored = []
    for sid, stats in strategy_stats.items():
        if not stats.get("active", True):
            continue
        score = score_strategy(stats)
        strategy_stats[sid]["score"] = score
        scored.append((sid, score, stats["trades"]))

    # Sort by score
    scored.sort(key=lambda x: x[1], reverse=True)

    log_entry = {
        "generation": generation,
        "ranking":    [(s[0], s[1]) for s in scored],
        "killed":     [],
        "evolved":    [],
    }

    # Only evolve if we have enough data (at least top strategy has 5+ trades)
    if scored and scored[0][2] >= 5:
        # Kill bottom 2 if they're losing
        for sid, score, trades in scored[-2:]:
            if score < 40 and trades >= 3:  # Clearly losing
                strategy_stats[sid]["active"] = False
                log_entry["killed"].append(sid)

        # Best strategy gets highest weight
        if scored:
            best_sid = scored[0][0]
            log_entry["evolved"].append(f"Champion: {best_sid} (score:{scored[0][1]})")

    return strategy_stats, log_entry


def get_strategy_signal(strategy_id, ind5m, ind1h, ind5m_safe=True):
    """
    Run a strategy's entry logic safely.
    Returns: direction ("BUY"/"SELL"/"HOLD"), confidence
    """
    if strategy_id not in STRATEGY_POOL:
        return "HOLD", 0

    s = STRATEGY_POOL[strategy_id]

    # HTF bias check
    trend_1h  = ind1h.get("trend", "RANGING_BEAR")
    htf_bull  = trend_1h in ["STRONG_BULL", "BULL", "RANGING_BULL"]
    htf_bear  = trend_1h in ["BEAR", "RANGING_BEAR"]
    above_1h  = ind1h.get("above_vwap", False)
    choch_b1h = ind1h.get("choch_bull", False)
    choch_br1h= ind1h.get("choch_bear", False)

    try:
        # Check bull entry
        if (not s["htf_required"] or (htf_bull and not choch_br1h)):
            if s["entry_bull"](ind5m, ind1h):
                conf = 7 if (htf_bull and above_1h) else 6
                return "BUY", conf

        # Check bear entry
        if (not s["htf_required"] or (htf_bear and not choch_b1h)):
            if s["entry_bear"](ind5m, ind1h):
                conf = 7 if (htf_bear and not above_1h) else 6
                return "SELL", conf

    except Exception as e:
        pass  # Graceful failure

    return "HOLD", 0


def get_best_active_strategy(strategy_stats):
    """Return the strategy with highest score that's active and has enough data"""
    best_sid = None
    best_score = -1

    for sid, stats in strategy_stats.items():
        if not stats.get("active", True):
            continue
        score = stats.get("score", 50)
        if score > best_score:
            best_score = score
            best_sid = sid

    return best_sid or "S6_MULTI_SIGNAL"  # fallback
