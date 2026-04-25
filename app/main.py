"""
AdaptiveBot PRO v8 — Self-Evolving AI Agent
- Free AI: Gemini → Groq → Claude → Rules
- 8 strategies compete live
- Every 2h: kills losing strategies, evolves winners
- Dynamic risk scaling by account size
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
import asyncio, os, time
from datetime import datetime

from app.state import state, lock, PAIRS, STARTING_BALANCE
from app.feed import stream
from app.indicators import compute
from app.brain import ask_ai
from app.execution import execute, manage_positions, daily_reset
from app.strategies import (init_strategy_stats, evaluate_and_evolve,
                             get_strategy_signal, get_best_active_strategy,
                             STRATEGY_POOL)

app = FastAPI()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
def ui():
    p = os.path.join(FRONTEND_DIR, "index.html")
    return FileResponse(p) if os.path.exists(p) else HTMLResponse("<h1>v8 running</h1>")

@app.head("/")
def h1(): return {}
@app.head("/data")
def h2(): return {}

@app.on_event("startup")
async def start():
    # Init strategy stats
    with lock:
        state["strategies"] = init_strategy_stats()
        state["active_strategy"] = {p: "S6_MULTI_SIGNAL" for p in PAIRS}
    asyncio.create_task(stream())
    asyncio.create_task(main_loop())
    asyncio.create_task(evolution_loop())
    keys = []
    if os.getenv("GEMINI_API_KEY"): keys.append("Gemini✓")
    if os.getenv("GROQ_API_KEY"):   keys.append("Groq✓")
    if os.getenv("CLAUDE_API_KEY"): keys.append("Claude✓")
    print(f"AdaptiveBot v8 | AI: {', '.join(keys) or 'Rules only'} | 8 strategies competing")


async def evolution_loop():
    """Every 2 hours: score strategies, kill losers, evolve winners"""
    await asyncio.sleep(7200)  # First evaluation after 2h
    while True:
        try:
            with lock:
                strats = dict(state["strategies"])
                gen    = state["generation"]

            strats, log_entry = evaluate_and_evolve(strats, gen)

            with lock:
                state["strategies"] = strats
                state["generation"] = gen + 1
                state["evolution_log"].insert(0, log_entry)
                if len(state["evolution_log"]) > 20:
                    state["evolution_log"].pop()
                # Update active strategies to best performers
                best = get_best_active_strategy(strats)
                for pair in PAIRS:
                    state["active_strategy"][pair] = best

            print(f"[EVOLVE] Gen {gen+1} | Best: {log_entry['ranking'][0] if log_entry['ranking'] else '?'} | Killed: {log_entry['killed']}")
        except Exception as e:
            print(f"[EVOLVE] Error: {e}")
        await asyncio.sleep(7200)  # Re-evaluate every 2h


async def main_loop():
    for _ in range(30):
        with lock:
            if any(v>0 for v in state["prices"].values()): break
        await asyncio.sleep(1)
    print(f"Prices loaded: {dict(state['prices'])}")

    last_ai = {p: 0 for p in PAIRS}
    AI_INTERVAL = 120  # Ask AI every 2 minutes

    while True:
        try:
            daily_reset()
            manage_positions()

            with lock:
                balance    = state["balance"]
                daily_loss = state["daily_loss"]
                positions  = state["positions"][:]

            # Live PnL
            live_pnl = 0
            for pos in positions:
                pr = state["prices"].get(pos["pair"],0)
                if pr>0:
                    p = (pr-pos["entry"])/pos["entry"]*pos["notional"] if pos["action"]=="BUY" \
                        else (pos["entry"]-pr)/pos["entry"]*pos["notional"]
                    live_pnl += p
            with lock: state["pnl"] = round(live_pnl,5)

            if daily_loss > balance*0.03:
                await asyncio.sleep(10); continue

            now = time.time()
            for pair in PAIRS:
                if now - last_ai[pair] < AI_INTERVAL: continue
                with lock:
                    price   = state["prices"][pair]
                    c5      = state["candles"][pair][:]
                    c1h     = state["candles_1h"][pair][:]
                    news    = dict(state["news"])
                    pair_pos= [p for p in state["positions"] if p["pair"]==pair]
                    active_sid = state["active_strategy"].get(pair,"S6_MULTI_SIGNAL")

                if price<=0 or len(c5)<20 or pair_pos: last_ai[pair]=now; continue

                i5  = compute(c5)
                i1  = compute(c1h) if len(c1h)>=20 else {}
                if not i5: last_ai[pair]=now; continue

                # Shadow-test all active strategies (paper track)
                with lock:
                    for sid in state["strategies"]:
                        if not state["strategies"][sid].get("active",True): continue
                        s_dir, s_conf = get_strategy_signal(sid, i5, i1)
                        state["strategies"][sid]["last_signal"] = s_dir

                # Get AI decision
                decision = ask_ai(pair, i5, i1, news, balance, positions)

                with lock:
                    state["ai_decision"][pair]  = decision["action"]
                    state["ai_reasoning"][pair] = f"[{decision.get('source','?')}] {decision.get('setup_type','')}: {decision.get('reasoning','')}"
                    state["ai_source"][pair]    = decision.get("source","?")

                last_ai[pair] = now

                if decision["action"] in ["BUY","SELL"] and decision["confidence"]>=6:
                    if not pair_pos and len(positions)<3:
                        ok = execute(pair, decision, i5, price, active_sid)
                        if ok:
                            with lock: positions = state["positions"][:]

        except Exception as e:
            import traceback; print(f"[MAIN]{e}"); traceback.print_exc()
        await asyncio.sleep(3)


@app.get("/data")
def get_data():
    with lock:
        pairs_out = {}
        for pair in PAIRS:
            pairs_out[pair] = {
                "price":     round(state["prices"][pair],4),
                "decision":  state["ai_decision"].get(pair,"HOLD"),
                "reasoning": state["ai_reasoning"].get(pair,""),
                "source":    state["ai_source"].get(pair,"?"),
                "strategy":  state["active_strategy"].get(pair,"?"),
            }
        positions = [{**p,"current":state["prices"].get(p["pair"],0)} for p in state["positions"]]
        strat_list = [
            {"id":sid,"name":s["name"],"trades":s["trades"],"wins":s["wins"],
             "win_rate":s.get("win_rate",0),"total_pnl":round(s.get("total_pnl",0),5),
             "score":round(s.get("score",50),1),"active":s.get("active",True)}
            for sid,s in state["strategies"].items()
        ]
        strat_list.sort(key=lambda x: x["score"], reverse=True)
        t=state["total_trades"]; w=state["winning_trades"]
        keys_active = []
        if os.getenv("GEMINI_API_KEY"): keys_active.append("Gemini")
        if os.getenv("GROQ_API_KEY"):   keys_active.append("Groq")
        if os.getenv("CLAUDE_API_KEY"): keys_active.append("Claude")
        return {
            "balance":      round(state["balance"],5),
            "initial":      STARTING_BALANCE,
            "total_pnl":    round(state["total_pnl"],5),
            "pnl":          round(state["pnl"],5),
            "win_rate":     round(w/t*100,1) if t>0 else 0,
            "total_trades": t, "winning":w, "losing":state["losing_trades"],
            "max_drawdown": state["max_drawdown"],
            "daily_trades": state["daily_trades"],
            "feed_status":  state["feed_status"],
            "ai_keys":      keys_active or ["Rules"],
            "generation":   state["generation"],
            "pairs":        pairs_out,
            "positions":    positions,
            "trades":       state["trades"][:30],
            "equity_curve": state["equity_curve"],
            "strategies":   strat_list,
            "evolution_log":state["evolution_log"][:5],
            "news":         state["news"],
        }
