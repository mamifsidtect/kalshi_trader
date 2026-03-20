#!/usr/bin/env python3
"""
Entry point: run backtests and signal tests on collected data.

Usage:
    python -m kalshi_trader.scripts.run_research --strategy MarketMaker --days 7
"""
import argparse
import os
import time
from datetime import datetime, timezone, timedelta
from kalshi_trader.config import load_config
from kalshi_trader.research.backtester import Backtester
from kalshi_trader.research.signal_tester import SignalTester
from kalshi_trader.strategies.market_maker import MarketMakerStrategy
from kalshi_trader.strategies.directional import DirectionalStrategy
from kalshi_trader.data.market_collector import MarketCollector
from kalshi_trader.data.models import ExternalSignals
from kalshi_trader.utils.logger import get_logger


def main():
    parser = argparse.ArgumentParser(description="Run backtests on collected Kalshi data")
    parser.add_argument(
        "--strategy", default="MarketMaker",
        choices=["MarketMaker", "Directional"],
        help="Strategy to backtest"
    )
    parser.add_argument("--days", type=int, default=7, help="Days of history to use")
    args = parser.parse_args()

    cfg = load_config()
    logger = get_logger("run_research", cfg.log_level)

    # Load snapshots from local storage
    collector = MarketCollector(None, cfg)
    snapshots = []
    for i in range(args.days):
        date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        date_dir = os.path.join(cfg.data_dir, date)
        if not os.path.exists(date_dir):
            continue
        for ticker in os.listdir(date_dir):
            snapshots.extend(collector.load_snapshots(ticker, date))

    if not snapshots:
        logger.warning("No snapshots found. Run collect_data.py first.")
        return

    logger.info(f"Loaded {len(snapshots)} snapshots across {args.days} days")

    # Signal tests
    tester = SignalTester(cfg)
    momentum_acc = tester.test_price_momentum(snapshots)
    spread_stats = tester.test_spread_liquidity(snapshots)
    logger.info(f"Price momentum accuracy: {momentum_acc:.1%}")
    logger.info(f"Spread stats: {spread_stats}")

    # Load external signals (use cache if available)
    from kalshi_trader.data.external_signals import ExternalSignalCollector
    sig_collector = ExternalSignalCollector(cfg)
    cached_signals = sig_collector.load_cached()
    if cached_signals:
        logger.info("Using cached external signals")
        signals_fn = lambda ts: cached_signals
    else:
        logger.info("No cached signals; using blank signals")
        blank = ExternalSignals(timestamp=int(time.time()))
        signals_fn = lambda ts: blank

    # Backtest
    strategy_map = {
        "MarketMaker": MarketMakerStrategy(min_volume=0),
        "Directional": DirectionalStrategy(),
    }
    strategy = strategy_map[args.strategy]
    bt = Backtester(cfg)
    result = bt.run(strategy, snapshots, signals_fn)

    logger.info(f"\n--- Backtest Results: {result.strategy_name} ---")
    logger.info(f"  Trades:       {result.total_trades}")
    logger.info(f"  Win Rate:     {result.win_rate:.1%}")
    logger.info(f"  Total P&L:    ${result.total_pnl:.2f}")
    logger.info(f"  Sharpe:       {result.sharpe:.2f}")
    logger.info(f"  Max Drawdown: ${result.max_drawdown:.2f}")
    logger.info(f"  Gate Passed:  {result.meets_promotion_gate(cfg)}")

    if result.trade_log:
        logger.info(f"\n  Sample trades (first 10):")
        for t in result.trade_log[:10]:
            logger.info(
                f"    {t['ticker']} {t['direction']} "
                f"entry={t['entry_price']}c exit={t['exit_price']}c "
                f"pnl=${t['pnl']:.2f}"
            )
    else:
        logger.info("  No trades were generated. Check strategy thresholds and data quality.")


if __name__ == "__main__":
    main()
