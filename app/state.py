import threading

lock = threading.Lock()

state = {
    # Market data
    "price": 0.0,
    "prices": [],          # rolling price history
    "candles": [],         # OHLCV candles from Kraken

    # Account
    "balance": 1000.0,
    "initial_balance": 1000.0,
    "positions": [],
    "pnl": 0.0,
    "total_pnl": 0.0,

    # Trade history — FIXED: stores full trade objects not just numbers
    "trades": [],

    # Signals
    "signals": {},
    "confidence": 0,
    "last_action": "NONE",
    "market_mode": "NORMAL",
    "trend": "neutral",

    # Risk controls
    "last_trade_time": 0,
    "daily_trades": 0,
    "daily_loss": 0.0,
    "daily_wins": 0,
    "daily_reset_hour": -1,

    # Connection status
    "feed_status": "connecting",
    "last_price_time": 0,

    # Stats
    "total_trades": 0,
    "winning_trades": 0,
    "losing_trades": 0,
    "max_drawdown": 0.0,
    "peak_balance": 1000.0,
}
