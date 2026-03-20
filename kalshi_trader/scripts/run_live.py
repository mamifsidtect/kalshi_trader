#!/usr/bin/env python3
"""
Entry point: run paper or live trading with web dashboard.

Usage:
    python -m kalshi_trader.scripts.run_live                     # paper mode
    EXECUTION_MODE=live python -m kalshi_trader.scripts.run_live  # live mode
"""
import threading
import time
from datetime import datetime, timezone
from kalshi_trader.config import load_config
from kalshi_trader.client.kalshi_client import KalshiClient
from kalshi_trader.data.market_collector import MarketCollector
from kalshi_trader.data.external_signals import ExternalSignalCollector
from kalshi_trader.strategies.market_maker import MarketMakerStrategy
from kalshi_trader.strategies.directional import DirectionalStrategy
from kalshi_trader.strategies.arbitrage import ArbitrageStrategy
from kalshi_trader.strategies.single_condition_arb import SingleConditionArbStrategy
from kalshi_trader.strategies.bregman_divergence import BregmanDivergenceStrategy
from kalshi_trader.risk.risk_manager import RiskManager
from kalshi_trader.execution.paper_trader import PaperTrader
from kalshi_trader.execution.live_trader import LiveTrader
from kalshi_trader.utils.logger import get_logger
from kalshi_trader.web.services.data_service import DataService
from collections import deque

SIGNAL_FEED = deque(maxlen=200)


def _update_correlated_prices(arb_strategy: ArbitrageStrategy, ext_signals) -> None:
    """Feed Polymarket-sourced probabilities into ArbitrageStrategy."""
    for ticker, prob in ext_signals.correlated_prices.items():
        arb_strategy.set_correlated_price(ticker, prob)


def trading_loop(cfg, client, risk_manager, executor, logger):
    market_collector = MarketCollector(client, cfg)
    signal_collector = ExternalSignalCollector(cfg)
    arb_strategy = ArbitrageStrategy()
    strategies = [
        MarketMakerStrategy(),
        DirectionalStrategy(),
        arb_strategy,
        SingleConditionArbStrategy(),
        BregmanDivergenceStrategy(),
    ]
    last_reset_date = datetime.now(timezone.utc).date()
    _data_service = DataService(cfg)

    while True:
        try:
            # Daily reset check
            today = datetime.now(timezone.utc).date()
            if today > last_reset_date:
                risk_manager.reset_daily()
                last_reset_date = today

            snapshots = market_collector.collect_once()
            ext_signals = signal_collector.collect()
            _update_correlated_prices(arb_strategy, ext_signals)

            # Check open positions for settlement or early exit
            strategy_map = {s.name: s for s in strategies}
            for ticker in list(risk_manager._open_positions.keys()):
                snap = next((s for s in snapshots if s.ticker == ticker), None)
                if snap is None:
                    continue
                meta = risk_manager.get_position_meta(ticker)
                if meta is None:
                    continue

                if snap.settled is not None:
                    # Market settled — close regardless of strategy.
                    # snap.settled=True means YES won (100c for YES, 0c for NO).
                    # snap.settled=False means NO won (0c for YES, 100c for NO).
                    yes_won = snap.settled
                    if meta.direction == "yes":
                        exit_price = 100 if yes_won else 0
                    else:
                        exit_price = 100 if not yes_won else 0
                    if cfg.execution_mode == "paper":
                        executor.close_position(ticker, exit_price)
                    risk_manager.close_position(ticker)
                    logger.info(
                        f"Settled close: {ticker} ({'YES' if yes_won else 'NO'} won) "
                        f"direction={meta.direction} @ {exit_price}c"
                    )

                else:
                    strategy = strategy_map.get(meta.strategy_name)
                    if strategy and strategy.on_exit(
                        meta.entry_price, meta.entry_ts, meta.direction, snap, ext_signals
                    ):
                        # Strategy requested early close
                        if cfg.execution_mode == "paper":
                            executor.close_position(ticker, int(snap.mid_price or meta.entry_price or 50))
                        else:
                            executor.close_position(ticker)
                        risk_manager.close_position(ticker)
                        logger.info(f"Early exit: {ticker} via {meta.strategy_name}")

            for snap in snapshots:
                for strategy in strategies:
                    signal = strategy.on_market_update(snap, ext_signals)
                    if signal is None:
                        continue

                    # Use live orderbook mid if available, else fall back to snapshot
                    live_mid = _data_service.get_live_mid_price(client, snap.ticker)
                    if signal.direction == "yes":
                        entry_price = int(live_mid) if live_mid is not None else (snap.yes_ask or 50)
                    else:
                        entry_price = int(100 - live_mid) if live_mid is not None else (snap.no_ask or 50)

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
                                signal.ticker,
                                cost,
                                category=snap.category,
                                entry_price=entry_price,
                                entry_ts=int(time.time()),
                                direction=signal.direction,
                                strategy_name=signal.strategy_name,
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
