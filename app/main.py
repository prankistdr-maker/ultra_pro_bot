async def trading_loop():
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
                price = state["price"]
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
                    "positions": state["positions"][:],
                    "balance": state["balance"],
                    "daily_trades": state["daily_trades"],
                    "daily_loss": state["daily_loss"],
                }

            action, confidence, mode, reasons, sl_pct, tp_pct = decide(
                ind, smc, current_state
            )

            # ─── UPDATE STATE ─────────────────────────
            live_pnl = 0

            with lock:
                for pos in state["positions"]:
                    if pos["action"] == "BUY":
                        pos_pnl = (price - pos["entry"]) / pos["entry"] * pos["amount"]
                    else:
                        pos_pnl = (pos["entry"] - price) / pos["entry"] * pos["amount"]

                    live_pnl += pos_pnl
                    pos["pnl"] = round(pos_pnl, 2)

                state["pnl"] = round(live_pnl, 4)
                state["signals"] = {**ind, **{"smc": smc}}
                state["confidence"] = confidence
                state["last_action"] = action
                state["market_mode"] = mode
                state["trend"] = ind.get("trend", "RANGING")

            # ─── EXECUTE TRADE ────────────────────────
            now = time.time()
            cooldown = 60 if mode == "SCALP" else 120

            with lock:
                last_trade = state["last_trade_time"]
                positions = state["positions"]

            if (
                action in ["BUY", "SELL"]
                and confidence >= 6
                and now - last_trade > cooldown
                and len(positions) < 2
            ):
                execute(action, sl_pct, tp_pct, confidence, reasons, mode)

        except Exception as e:
            print(f"BOT ERROR: {e}")
