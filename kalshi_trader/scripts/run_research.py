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
from kalshi_trader.research.parameter_sweeper import ParameterSweeper
from kalshi_trader.strategies.market_maker import MarketMakerStrategy
from kalshi_trader.strategies.directional import DirectionalStrategy
from kalshi_trader.strategies.single_condition_arb import SingleConditionArbStrategy
from kalshi_trader.strategies.bregman_divergence import BregmanDivergenceStrategy
from kalshi_trader.data.market_collector import MarketCollector
from kalshi_trader.data.models import ExternalSignals
from kalshi_trader.utils.logger import get_logger


def main():
    parser = argparse.ArgumentParser(description="Run backtests on collected Kalshi data")
    parser.add_argument(
        "--strategy", default="MarketMaker",
        choices=["MarketMaker", "Directional", "SingleConditionArb", "BregmanDivergence"],
        help="Strategy to backtest"
    )
    parser.add_argument("--days", type=int, default=7, help="Days of history to use")
    parser.add_argument("--backfill", action="store_true",
                        help="Backfill settlement data from Kalshi API before running backtest")
    parser.add_argument("--sweep", action="store_true",
                        help="Auto-sweep parameters if default config fails promotion gate")
    parser.add_argument("--sweep-all", action="store_true",
                        help="Sweep parameters for all strategies")
    parser.add_argument("--rank-by", default="sharpe", choices=["sharpe", "win_rate"],
                        help="Metric to rank sweep results by (default: sharpe)")
    parser.add_argument("--vwap-slippage", action="store_true",
                        help="Use VWAP-based slippage model instead of fixed 1c slippage")
    args = parser.parse_args()

    cfg = load_config()
    logger = get_logger("run_research", cfg.log_level)

    # Load snapshots from local storage
    logger.info(f"Loading snapshots from last {args.days} days...")
    collector = MarketCollector(None, cfg)
    snapshots = []
    dates_found = 0
    tickers_seen = set()
    for i in range(args.days):
        date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        date_dir = os.path.join(cfg.data_dir, date)
        if not os.path.exists(date_dir):
            logger.info(f"  {date}: no data directory")
            continue
        date_tickers = os.listdir(date_dir)
        date_snap_count = 0
        for ticker in date_tickers:
            loaded = collector.load_snapshots(ticker, date)
            snapshots.extend(loaded)
            date_snap_count += len(loaded)
            tickers_seen.add(ticker)
        dates_found += 1
        logger.info(f"  {date}: {len(date_tickers)} tickers, {date_snap_count} snapshots")

    if not snapshots:
        logger.warning("No snapshots found. Run collect_data.py first.")
        return

    settled_count = sum(1 for s in snapshots if s.settled is not None)
    logger.info(
        f"Loaded {len(snapshots)} snapshots | "
        f"{dates_found} days | "
        f"{len(tickers_seen)} unique tickers | "
        f"{settled_count} with settlement data"
    )

    if args.backfill:
        logger.info("Starting settlement data backfill...")
        from kalshi_trader.client.kalshi_client import KalshiClient
        client = KalshiClient(cfg)
        for i in range(args.days):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            logger.info(f"  Backfilling {date}...")
            backfill_collector = MarketCollector(client, cfg)
            backfill_collector.backfill_settlement(date)
        # Reload snapshots after backfill
        logger.info("Reloading snapshots after backfill...")
        snapshots = []
        for i in range(args.days):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            date_dir = os.path.join(cfg.data_dir, date)
            if not os.path.exists(date_dir):
                continue
            for ticker in os.listdir(date_dir):
                snapshots.extend(collector.load_snapshots(ticker, date))
        settled_after = sum(1 for s in snapshots if s.settled is not None)
        logger.info(
            f"After backfill: {len(snapshots)} snapshots | "
            f"{settled_after} with settlement data"
        )

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

    # Sweep all strategies if requested
    if args.sweep_all:
        sweeper = ParameterSweeper(cfg)
        reports = sweeper.sweep_all(snapshots, signals_fn, rank_by=args.rank_by)
        for name, report in reports.items():
            _log_sweep_report(logger, name, report)
        return

    # Backtest with default params
    strategy_map = {
        "MarketMaker": MarketMakerStrategy(min_volume=0),
        "Directional": DirectionalStrategy(),
        "SingleConditionArb": SingleConditionArbStrategy(),
        "BregmanDivergence": BregmanDivergenceStrategy(),
    }
    strategy = strategy_map[args.strategy]
    bt = Backtester(cfg, vwap_slippage=args.vwap_slippage)
    result = bt.run(strategy, snapshots, signals_fn)

    _log_backtest_result(logger, result, cfg)

    # Auto-sweep if default params failed the gate
    if not result.meets_promotion_gate(cfg) and args.sweep:
        logger.info(
            f"\nDefault {args.strategy} params failed promotion gate. "
            f"Starting automatic parameter sweep..."
        )
        sweeper = ParameterSweeper(cfg)
        report = sweeper.sweep(args.strategy, snapshots, signals_fn, rank_by=args.rank_by)
        _log_sweep_report(logger, args.strategy, report)


def _log_backtest_result(logger, result, cfg):
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


def _log_sweep_report(logger, strategy_name, report):
    promoted = report.promoted_results
    logger.info(f"\n--- Sweep Report: {strategy_name} ---")
    logger.info(f"  Combinations tested: {report.total_combinations}")
    logger.info(f"  Configs passing gate: {len(promoted)}")

    if report.best:
        b = report.best
        logger.info(f"  >>> BEST PROMOTABLE CONFIG <<<")
        for k, v in b.params.items():
            logger.info(f"      {k}: {v}")
        logger.info(
            f"    Sharpe={b.backtest.sharpe:.2f}  Win={b.backtest.win_rate:.1%}  "
            f"PnL=${b.backtest.total_pnl:.2f}  Trades={b.backtest.total_trades}  "
            f"MaxDD=${b.backtest.max_drawdown:.2f}"
        )
    else:
        logger.info("  No configuration passed the promotion gate.")
        top = report.all_results[:5]
        if top:
            logger.info("  Top 5 (closest to gate):")
            for i, r in enumerate(top, 1):
                logger.info(
                    f"    #{i} {r.params} — "
                    f"Sharpe={r.backtest.sharpe:.2f}  "
                    f"Win={r.backtest.win_rate:.1%}  "
                    f"Trades={r.backtest.total_trades}"
                )


if __name__ == "__main__":
    main()
