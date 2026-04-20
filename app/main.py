"""AdaptiveBot PRO v7 — Claude AI Brain"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
import asyncio, os, time
from datetime import datetime

from app.state import state, lock, PAIRS, STARTING_BALANCE
from app.feed import stream
from app.brain import compute_indicators, ask_claude
from app.execution import execute, manage_positions, daily_reset

app = FastAPI()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
def ui():
    p = os.path.join(FRONTEND_DIR, "index.html")
    return FileResponse(p) if os.path.exists(p) else HTMLResponse("<h1>Bot v7 running</h1>")

@app.head("/")
def h1(): return {}
@app.head("/data")
def h2(): return {}

@app.on_event("startup")
async def start():
    asyncio.create_task(stream())
    asyncio.create_task(main_loop())
    import os
    key = os.getenv("CLAUDE_API_KEY","")
    print(f"AdaptiveBot v7 — Claude AI Brain | Key: {'✓ active' if key else '✗ missing (rule-based fallback)'}")

async def main_loop():

    # Add inside main_loop, before trading logic:

# Daily profit target – stop trading after +5%
daily_pnl = state["balance"] - state["initial_balance"]
if daily_pnl >= state["initial_balance"] * 0.05:
    print(f"Daily profit target reached (+${daily_pnl:.2f}). Sleeping.")
    await asyncio.sleep(60)
    continue

# Daily loss limit already present.

# Session filter (re-check here even if Claude was called)
session = get_session()
if session == "LOW_VOLUME":
    await asyncio.sleep(10)
    continue

# Minimum ATR filter
atr_pct = ind5m.get("atr_pct", 0)
if atr_pct < 0.25:
    continue   # pair too dead

# Cooldown after loss
if recent_trades and recent_trades[0]["pnl"] < 0:
    if time.time() - recent_trades[0]["time"] < 600:   # 10 min
        continue
    for _ in range(30):
        with lock:
            if any(v>0 for v in state["prices"].values()): break
        await asyncio.sleep(1)

    print(f"Prices: {dict(state['prices'])}")

    last_claude_call = {p: 0 for p in PAIRS}
    CLAUDE_INTERVAL = 120  # Ask Claude every 2 minutes

    while True:
        try:
            daily_reset()
            manage_positions()

            with lock:
                balance   = state["balance"]
                positions = state["positions"][:]
                daily_loss= state["daily_loss"]

            live_pnl = 0
            for pos in positions:
                pr = state["prices"].get(pos["pair"], 0)
                if pr > 0:
                    p = (pr-pos["entry"])/pos["entry"]*pos["amount"] if pos["action"]=="BUY" \
                        else (pos["entry"]-pr)/pos["entry"]*pos["amount"]
                    live_pnl += p
            with lock:
                state["pnl"] = round(live_pnl, 5)

            # Stop if 3% daily loss
            if daily_loss > balance * 0.03:
                await asyncio.sleep(10)
                continue

            for pair in PAIRS:
                now = time.time()
                if now - last_claude_call[pair] < CLAUDE_INTERVAL:
                    continue

                with lock:
                    price   = state["prices"][pair]
                    c5      = state["candles"][pair][:]
                    c1h     = state["candles_1h"][pair][:]
                    news    = dict(state["news"])
                    trades  = state["trades"][:10]
                    pair_positions = [p for p in state["positions"] if p["pair"]==pair]

                if price <= 0 or len(c5) < 20:
                    continue

                # Skip if position already open on this pair
                if pair_positions:
                    last_claude_call[pair] = now
                    continue

                ind5m = compute_indicators(c5)
                ind1h = compute_indicators(c1h) if len(c1h)>=20 else {}

                # Ask Claude AI
                decision = ask_claude(pair, ind5m, ind1h, news, balance, positions, trades)

                # Store reasoning for display
                with lock:
                    state["ai_reasoning"][pair] = f"{decision.get('setup_type','')}: {decision.get('reasoning','')}"
                    state["decision"][pair] = decision["action"]

                last_claude_call[pair] = now

                # Execute if Claude says trade
                if decision["action"] in ["BUY","SELL"] and decision["confidence"] >= 6:
                    if not pair_positions and len(positions) < 3:
                        executed = execute(pair, decision, ind5m, price)
                        if executed:
                            with lock:
                                positions = state["positions"][:]

        except Exception as e:
            import traceback; print(f"[MAIN] {e}"); traceback.print_exc()
        await asyncio.sleep(3)


@app.get("/data")
def get_data():
    with lock:
        pairs_out = {}
        for pair in PAIRS:
            p = state["prices"][pair]
            pairs_out[pair] = {
                "price":      round(p,4),
                "decision":   state["decision"][pair],
                "reasoning":  state["ai_reasoning"][pair],
            }
        positions = []
        for pos in state["positions"]:
            pr = state["prices"].get(pos["pair"],0)
            positions.append({**pos,"current":pr})
        total = state["total_trades"]; wins = state["winning_trades"]
        import os
        return {
            "balance":      round(state["balance"],5),
            "initial":      STARTING_BALANCE,
            "total_pnl":    round(state["total_pnl"],5),
            "pnl":          round(state["pnl"],5),
            "win_rate":     round(wins/total*100,1) if total>0 else 0,
            "total_trades": total, "winning": wins, "losing": state["losing_trades"],
            "max_drawdown": state["max_drawdown"],
            "daily_trades": state["daily_trades"],
            "feed_status":  state["feed_status"],
            "has_claude":   bool(os.getenv("CLAUDE_API_KEY","")),
            "pairs":        pairs_out,
            "positions":    positions,
            "trades":       state["trades"][:30],
            "equity_curve": state["equity_curve"],
            "news":         state["news"],
        }
