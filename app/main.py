"""AdaptiveBot PRO v6 - ICT Silver Bullet Strategy"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
import asyncio, os, time
from datetime import datetime

from app.state import state, lock, PAIRS, STARTING_BALANCE
from app.feed import stream
from app.indicators import compute
from app.engine import decide, get_kill_zone, get_htf_bias
from app.execution import execute, manage_positions, daily_reset
from app.news import refresh_news, get_news_score

app = FastAPI()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
def serve_ui():
    p = os.path.join(FRONTEND_DIR, "index.html")
    return FileResponse(p) if os.path.exists(p) else HTMLResponse("<h1>AdaptiveBot v6</h1>")

@app.head("/")
def h1(): return {}
@app.head("/data")
def h2(): return {}

@app.on_event("startup")
async def start():
    asyncio.create_task(stream())
    asyncio.create_task(refresh_news())
    asyncio.create_task(main_loop())
    print("AdaptiveBot PRO v6 — ICT Silver Bullet | Kill Zones | Liq+MSS+FVG")

async def main_loop():
    for _ in range(30):
        with lock:
            if any(v > 0 for v in state["prices"].values()): break
        await asyncio.sleep(1)
    print(f"Live prices: {dict(state['prices'])}")

    while True:
        try:
            daily_reset()
            manage_positions()

            session, sq = get_kill_zone()
            with lock:
                state["session"] = f"{session}(q{sq})"

            with lock:
                balance = state["balance"]; daily_loss = state["daily_loss"]
                daily_trades = state["daily_trades"]; positions = state["positions"][:]

            live_pnl = 0
            for pos in positions:
                pr = state["prices"].get(pos["pair"], 0)
                if pr > 0:
                    p = (pr-pos["entry"])/pos["entry"]*pos["amount"] if pos["action"]=="BUY" \
                        else (pos["entry"]-pr)/pos["entry"]*pos["amount"]
                    live_pnl += p
            with lock:
                state["pnl"] = round(live_pnl, 5)

            for pair in PAIRS:
                with lock:
                    price = state["prices"][pair]
                    c5    = state["candles"][pair][:]
                    c1h   = state["candles_1h"][pair][:]
                    last_tt = state["last_trade_time"][pair]

                if price <= 0 or len(c5) < 30:
                    continue

                ind = compute(c5)
                if not ind:
                    continue

                # HTF bias
                htf_bias, _ = get_htf_bias(c1h)
                with lock:
                    state["htf_bias"][pair] = htf_bias

                direction, conf, mode, reasons, sl_pct, tp_pct, sl_price, tp_price = decide(
                    pair, ind, c5, c1h, balance, positions, daily_loss, daily_trades, last_tt
                )

                with lock:
                    state["ind"][pair]      = ind
                    state["decision"][pair] = direction
                    state["mode"][pair]     = mode
                    state["conf"][pair]     = conf
                    state["reasons"][pair]  = reasons

                if direction in ["BUY","SELL"] and conf >= 6:
                    if not [p for p in positions if p["pair"]==pair]:
                        execute(pair, direction, sl_pct, tp_pct, sl_price, tp_price,
                                conf, reasons, mode, ind)
                        with lock: positions = state["positions"][:]

        except Exception as e:
            import traceback; print(f"[MAIN] {e}"); traceback.print_exc()
        await asyncio.sleep(3)


@app.get("/data")
def get_data():
    with lock:
        pairs_out = {}
        for pair in PAIRS:
            p = state["prices"][pair]
            ind = state["ind"].get(pair, {})
            pairs_out[pair] = {
                "price": round(p,4), "rsi": ind.get("rsi",0),
                "trend": ind.get("trend","RANGING"),
                "macd_hist": ind.get("macd_hist",0),
                "atr_pct": ind.get("atr_pct",0),
                "mode": state["mode"][pair],
                "decision": state["decision"][pair],
                "conf": state["conf"][pair],
                "reasons": state["reasons"][pair],
                "ema_bull": ind.get("ema_bull",False),
                "above_vwap": ind.get("above_vwap",False),
                "volatility": ind.get("volatility","low"),
                "htf_bias": state["htf_bias"].get(pair,"neutral"),
            }
        positions = []
        for pos in state["positions"]:
            pr = state["prices"].get(pos["pair"],0)
            positions.append({**pos, "current": pr})
        from app.news import _cache as nc
        total = state["total_trades"]; wins = state["winning_trades"]
        return {
            "balance": round(state["balance"],5), "initial": STARTING_BALANCE,
            "total_pnl": round(state["total_pnl"],5), "pnl": round(state["pnl"],5),
            "win_rate": round(wins/total*100,1) if total>0 else 0,
            "total_trades": total, "winning": wins, "losing": state["losing_trades"],
            "max_drawdown": state["max_drawdown"], "daily_trades": state["daily_trades"],
            "daily_loss": round(state["daily_loss"],5), "feed_status": state["feed_status"],
            "session": state.get("session","--"),
            "pairs": pairs_out, "positions": positions,
            "trades": state["trades"][:30], "equity_curve": state["equity_curve"],
            "news": {"fg_index": nc.get("fg_index",50), "fg_label": nc.get("fg_label","neutral"),
                     "events": nc.get("events",[])[:4], "trending": nc.get("trending",[])[:5]},
        }
