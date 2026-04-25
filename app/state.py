import threading
lock = threading.Lock()
PAIRS = {
    "BTCUSDT": {"kraken": "XBTUSD"},
    "ETHUSDT": {"kraken": "ETHUSD"},
    "SOLUSDT": {"kraken": "SOLUSD"},
}
STARTING_BALANCE = 20.0
state = {
    "balance": STARTING_BALANCE,
    "initial_balance": STARTING_BALANCE,
    "peak_balance": STARTING_BALANCE,
    "total_pnl": 0.0,
    "pnl": 0.0,
    "positions": [],
    "trades": [],
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    "max_drawdown": 0.0,
    "daily_trades": 0,
    "daily_wins": 0,
    "daily_loss": 0.0,
    "daily_reset_hour": -1,
    "prices":     {p: 0.0 for p in PAIRS},
    "candles":    {p: []  for p in PAIRS},
    "candles_1h": {p: []  for p in PAIRS},
    "feed_status": "connecting",
    "equity_curve": [{"t": "start", "v": STARTING_BALANCE}],
    # AI decisions per pair
    "ai_decision":  {p: "HOLD" for p in PAIRS},
    "ai_reasoning": {p: "Initializing..." for p in PAIRS},
    "ai_source":    {p: "none" for p in PAIRS},
    "last_trade_time": {p: 0 for p in PAIRS},
    "news": {"fg": 50, "fg_label": "neutral"},
    # Strategy evolution engine
    "strategies": {},        # strategy_id -> stats
    "active_strategy": {},   # pair -> strategy_id
    "evolution_log": [],     # history of strategy switches
    "generation": 1,         # which generation of strategies we're on
}
