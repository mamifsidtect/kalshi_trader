#!/usr/bin/env python3
"""
Entry point: run paper or live trading with web dashboard.

Usage:
    python -m kalshi_trader.scripts.run_live                     # paper mode
    EXECUTION_MODE=live python -m kalshi_trader.scripts.run_live  # live mode
"""
import threading
import time
from kalshi_trader.config import load_config
from kalshi_trader.client.kalshi_client import KalshiClient
from kalshi_trader.data.market_collector import MarketCollector
from kalshi_trader.data.external_signals import ExternalSignalCollector
from kalshi_trader.strategies.market_maker import MarketMakerStrategy
from kalshi_trader.strategies.directional import DirectionalStrategy
from kalshi_trader.risk.risk_manager import RiskManager
from kalshi_trader.execution.paper_trader import PaperTrader
from kalshi_trader.execution.live_trader import LiveTrader
from kalshi_trader.utils.logger import get_logger
from collections import deque

SIGNAL_FEED = deque(maxlen=200)


def trading_loop(cfg, client, risk_manager, executor, logger):
    from datetime import datetime, timezone
    market_collector = MarketCollector(client, cfg)
    signal_collector = ExternalSignalCollector(cfg)
    strategies = [MarketMakerStrategy(), DirectionalStrategy()]
    last_reset_date = datetime.now(timezone.utc).date()

    while True:
        try:
            # Daily reset check
            today = datetime.now(timezone.utc).date()
            if today > last_reset_date:
                risk_manager.reset_daily()
                last_reset_date = today

            snapshots = market_collector.collect_once()
            ext_signals = signal_collector.collect()

            for snap in snapshots:
                for strategy in strategies:
                    signal = strategy.on_market_update(snap, ext_signals)
                    if signal is None:
                        continue

                    # Use correct side price
                    if signal.direction == "yes":
                        entry_price = snap.yes_ask or 50
                    else:
                        entry_price = snap.no_ask or 50

                    approved, reason = risk_manager.validate(
                        signal, current_price=entry_price, category=snap.category
                    )
                    feed_entry = {
                        "ticker": signal.ticker,
                        "direction": signal.direction,
                        "confidence": signal.confidence,
                        "strategy": signal.strategy_name,
                        "reason": reason,
                        "approved": approved,
                    }
                    SIGNAL_FEED.append(feed_entry)

                    if approved:
                        # Size position from risk manager
                        signal.size = risk_manager.size_position(entry_price)
                        result = executor.execute(signal, current_price=entry_price)
                        if result.get("status") not in ("rejected",):
                            cost = signal.size * (entry_price / 100.0)
                            risk_manager.record_open_position(
                                signal.ticker, cost, category=snap.category
                            )

        except KeyboardInterrupt:
            logger.info("Trading loop stopped by user")
            break
        except Exception as e:
            logger.error(f"Trading loop error: {e}")

        time.sleep(cfg.collection_interval_seconds)


def main():
    cfg = load_config()
    logger = get_logger("run_live", cfg.log_level)
    client = KalshiClient(cfg)

    # Placeholder bankroll — replace with actual account balance query
    bankroll = 1000.0
    risk_manager = RiskManager(cfg, bankroll=bankroll)

    if cfg.execution_mode == "live":
        logger.warning("LIVE TRADING MODE ENABLED")
        executor = LiveTrader(client, cfg)
    else:
        logger.info("Paper trading mode")
        executor = PaperTrader(cfg, initial_bankroll=bankroll)

    if cfg.dashboard_enabled:
        from kalshi_trader.web.app import create_app
        import uvicorn
        app = create_app(
            cfg,
            paper_trader=executor if cfg.execution_mode == "paper" else None,
            signal_feed=SIGNAL_FEED,
        )
        dashboard_thread = threading.Thread(
            target=uvicorn.run,
            args=(app,),
            kwargs={"host": "0.0.0.0", "port": cfg.dashboard_port, "log_level": "warning"},
            daemon=True,
        )
        dashboard_thread.start()
        logger.info(f"Dashboard running at http://localhost:{cfg.dashboard_port}")

    logger.info("Starting trading loop")
    trading_loop(cfg, client, risk_manager, executor, logger)


if __name__ == "__main__":
    main()
