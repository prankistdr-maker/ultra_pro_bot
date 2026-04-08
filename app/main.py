from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio
import pandas as pd
import os

from app.state import state
from app.feed import stream
from app.indicators import compute
from app.smc import market_structure, liquidity_sweep, order_block, fvg
from app.engine import decide
from app.execution import execute

app = FastAPI()

# 📁 Setup frontend path (IMPORTANT)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

# Serve UI
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
def serve_ui():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

# Store prices
prices = []

# 🚀 START BOT ON SERVER START
@app.on_event("startup")
async def start():
    asyncio.create_task(main_loop())

# 🔥 MAIN LOOP (STABLE VERSION)
import datetime

# reset daily loss at midnight UTC
if datetime.datetime.utcnow().hour == 0:
    state["daily_loss"] = 0
    state["daily_trades"] = 0


async def main_loop():
    asyncio.create_task(stream())  # start websocket

    while True:
        try:
            price = state["price"]

            if price > 0:
                prices.append(price)

                # Keep last 200 prices
                if len(prices) > 200:
                    prices.pop(0)

                # Wait for enough data
                if len(prices) < 30:
                    await asyncio.sleep(1)
                    continue

                # DataFrame
                df = pd.DataFrame(prices, columns=["close"])
                df = compute(df)

                # Safe RSI
                rsi_val = df["rsi"].iloc[-1]
                if pd.isna(rsi_val):
                    rsi_val = 50

                # Signals
                signals = {
                    "trend": "bullish" if df["ema50"].iloc[-1] > df["ema200"].iloc[-1] else "bearish",
                    "rsi": float(rsi_val),
                    "structure": market_structure(prices),
                    "liquidity": liquidity_sweep(prices),
                    "ob": order_block(prices),
                    "fvg": fvg(prices)
                }

                # Decision
                action, confidence = decide(signals)

                # Execute trade
                if action != state["last_action"]:
                    execute(action)
                    state["last_action"] = action

                # Save state
                state["signals"] = signals
                state["confidence"] = confidence

        except Exception as e:
            print("BOT ERROR:", e)

        await asyncio.sleep(2)  # avoid overload

# 📊 API (SAFE JSON)
@app.get("/data")
def get_data():

    def clean(obj):
        if isinstance(obj, float):
            if obj != obj:  # NaN check
                return 0
        return obj

    clean_state = {}

    for k, v in state.items():
        if isinstance(v, dict):
            clean_state[k] = {kk: clean(vv) for kk, vv in v.items()}
        elif isinstance(v, list):
            clean_state[k] = [clean(i) for i in v]
        else:
            clean_state[k] = clean(v)

    return clean_state
