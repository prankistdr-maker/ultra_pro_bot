import asyncio, websockets, json
from app.state import state

async def stream():
    url = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"

    while True:
        try:
            async with websockets.connect(url, ping_interval=20) as ws:
                while True:
                    data = json.loads(await ws.recv())
                    state["price"] = float(data["p"])

        except Exception as e:
            print("WebSocket reconnecting...", e)
            await asyncio.sleep(5)