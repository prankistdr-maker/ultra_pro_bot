"""
AdaptiveBot PRO - Main Application
FastAPI + Real-time AI Trading Agent
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
import asyncio
import os
import time

from app.state import state, lock
from app.feed import stream
from app.indicators import compute
from app.smc import analyze_smc
from app.engine import decide
from app.execution import execute, manage_positions, daily_reset

app = FastAPI()

# Frontend
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    return HTMLResponse("<h1>Bot Running</h1><p>Check /data for status</p>")


@app.head("/")
def head_root():
    return {}


@app.head("/data")
def head_data():
    return {}


@app.on_event("startup")
async def start():
    asyncio.create_task(main_loop())
    print("AdaptiveBot PRO started")


async def main_loop():
    """Main bot loop"""
    # Start price feed
    asyncio.create_task(stream())

    # Wait for initial data
    print("Waiting for price data...")
    for _ in range(30):
        with lock:
            price = state["price"]
        if price > 0:
            break
        await asyncio.sleep(1)

    print(f"Price loaded: ${state['price']:,.2f}")

    last_trade_check = 0

    while True:
        try:
            with lock:
                price   = state["price"]
                candles = state["candles"][:]

            if price <= 0 or len(candles) < 30:
                await asyncio.sleep(2)
                continue

            # ─── DAILY RESET ──────────────────────────
            daily_reset()

            # ─── MANAGE OPEN POSITIONS ────────────────
            manage_positions()

            # ─── CALCULATE INDICATORS ─────────────────
            ind = compute(candles)

            # ─── SMC ANALYSIS ─────────────────────────
            smc = analyze_smc(candles)

            # ─── AI DECISION ──────────────────────────
            with lock:
                current_state = {
                    "positions":    state["positions"][:],
                    "balance":      state["balance"],
                    "daily_trades": state["daily_trades"],
                    "daily_loss":   state["daily_loss"],
                }

            action, confidence, mode, reasons, sl_pct, tp_pct = decide(
                ind, smc, current_state
            )

            # ─── UPDATE STATE ─────────────────────────
            # Live PnL for open positions
            live_pnl = 0
            with lock:
                for pos in state["positions"]:
                    if pos["action"] == "BUY":
                        pos_pnl = (price - pos["entry"]) / pos["entry"] * pos["amount"]
                    else:
                        pos_pnl = (pos["entry"] - price) / pos["entry"] * pos["amount"]
                    live_pnl += pos_pnl
                    pos["pnl"] = round(pos_pnl, 2)

                state["pnl"]         = round(live_pnl, 4)
                state["signals"]     = {**ind, **{"smc": smc}}
                state["confidence"]  = confidence
                state["last_action"] = action
                state["market_mode"] = mode
                state["trend"]       = ind.get("trend", "RANGING")

            # ─── EXECUTE TRADE ────────────────────────
            now = time.time()
            cooldown = 60 if mode == "SCALP" else 120

            with lock:
                last_trade = state["last_trade_time"]
                positions  = state["positions"]

            if (action in ["BUY", "SELL"] and
                    confidence >= 6 and
                    now - last_trade > cooldown and
                    len(positions) < 2):

                execute(action, sl_pct, tp_pct, confidence, reasons, mode)

        except Exception as e:
            print(f"BOT ERROR: {e}")
            import traceback
            traceback.print_exc()

        await asyncio.sleep(3)


@app.get("/data")
def get_data():
    """Dashboard data endpoint"""
    with lock:
        price   = state["price"]
        balance = state["balance"]
        pnl     = state["pnl"]

        total_trades   = state["total_trades"]
        winning_trades = state["winning_trades"]
        losing_trades  = state["losing_trades"]
        win_rate       = round(winning_trades / total_trades * 100, 1) if total_trades > 0 else 0

        # Safe signal extraction
        signals = state.get("signals", {})
        safe_signals = {}
        for k, v in signals.items():
            if k == "smc":
                continue  # Skip nested dict for simplicity
            if isinstance(v, (int, float, bool, str)):
                safe_signals[k] = v if v == v else 0  # NaN check

        # Positions (safe)
        positions = []
        for pos in state["positions"]:
            positions.append({
                "id":         pos["id"],
                "action":     pos["action"],
                "entry":      pos["entry"],
                "current":    price,
                "pnl":        round(pos.get("pnl", 0), 2),
                "sl":         round(pos["sl"], 2),
                "tp":         round(pos["tp"], 2),
                "mode":       pos.get("mode", ""),
                "confidence": pos.get("confidence", 0),
                "time":       pos.get("time_str", ""),
                "reasons":    pos.get("reasons", [])
            })

        return {
            # Core
            "price":       round(price, 2),
            "balance":     round(balance, 2),
            "pnl":         round(pnl, 2),
            "total_pnl":   round(state["total_pnl"], 2),

            # Stats
            "total_trades":   total_trades,
            "winning_trades": winning_trades,
            "losing_trades":  losing_trades,
            "win_rate":       win_rate,
            "max_drawdown":   state["max_drawdown"],
            "daily_trades":   state["daily_trades"],

            # Decision
            "last_action": state["last_action"],
            "confidence":  state["confidence"],
            "market_mode": state["market_mode"],
            "trend":       state["trend"],
            "feed_status": state["feed_status"],

            # Signals (safe subset)
            "signals": safe_signals,

            # Positions
            "positions": positions,

            # Trade history — FULLY FIXED
            "trades": state["trades"][:20],  # Last 20 trades
        }
