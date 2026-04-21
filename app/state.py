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
    "ai_reasoning": {p: "Waiting..." for p in PAIRS},
    "decision":   {p: "HOLD" for p in PAIRS},
    "last_trade_time": {p: 0 for p in PAIRS},
    "feed_status": "connecting",
    "equity_curve": [{"t": "start", "v": STARTING_BALANCE}],
    "news": {"fg": 50, "fg_label": "neutral", "headlines": []},
    # New: leverage and margin tracking
    "margin_used": 0.0,
    "max_leverage": 50,
    "current_leverage": {p: 1 for p in PAIRS},
}
