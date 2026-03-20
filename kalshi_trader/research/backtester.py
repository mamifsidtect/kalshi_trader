import hashlib
import math
from dataclasses import dataclass, field
from typing import List, Callable, Dict, Optional
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals
from kalshi_trader.strategies.base_strategy import BaseStrategy
from kalshi_trader.config import KalshiConfig
from kalshi_trader.utils.logger import get_logger


@dataclass
class BacktestResult:
    strategy_name: str
    total_trades: int
    win_rate: float
    total_pnl: float
    sharpe: float
    max_drawdown: float
    avg_hold_bars: float
    trade_log: List[Dict] = field(default_factory=list)

    def meets_promotion_gate(self, cfg: KalshiConfig) -> bool:
        return self.sharpe >= cfg.min_backtest_sharpe and self.win_rate >= cfg.min_backtest_win_rate


class Backtester:
    SLIPPAGE_CENTS = 1  # 1 cent slippage on fills

    def __init__(self, config: KalshiConfig, vwap_slippage: bool = False):
        self.config = config
        self.vwap_slippage = vwap_slippage
        self.logger = get_logger(__name__, config.log_level)

    def run(
        self,
        strategy: BaseStrategy,
        snapshots: List[MarketSnapshot],
        signals_fn: Callable[[int], ExternalSignals],
        slippage: Optional[int] = None,
        progress_callback: Optional[Callable[[Dict], None]] = None,
    ) -> BacktestResult:
        slippage = slippage if slippage is not None else self.SLIPPAGE_CENTS

        # Group snapshots by ticker to avoid cross-ticker contamination
        by_ticker: Dict[str, List[MarketSnapshot]] = {}
        for snap in snapshots:
            by_ticker.setdefault(snap.ticker, []).append(snap)

        total_tickers = len(by_ticker)
        total_snapshots = len(snapshots)
        self.logger.info(
            f"Starting backtest: {strategy.name} | "
            f"{total_snapshots} snapshots across {total_tickers} tickers"
        )

        all_trades: List[Dict] = []
        all_pnl: List[float] = []
        signals_evaluated = 0
        signals_skipped = 0

        for idx, (ticker, ticker_snaps) in enumerate(by_ticker.items(), 1):
            self.logger.info(
                f"  [{idx}/{total_tickers}] Processing {ticker} "
                f"({len(ticker_snaps)} snapshots)"
            )
            trades, pnl, stats = self._run_single_ticker(
                strategy, ticker_snaps, signals_fn, slippage
            )
            all_trades.extend(trades)
            all_pnl.extend(pnl)
            signals_evaluated += stats["evaluated"]
            signals_skipped += stats["skipped"]

            if trades:
                ticker_pnl = sum(t["pnl"] for t in trades)
                self.logger.info(
                    f"           -> {len(trades)} trades, "
                    f"P&L: ${ticker_pnl:.2f}"
                )

            if progress_callback:
                progress_callback({
                    "phase": "backtest",
                    "ticker": ticker,
                    "tickers_done": idx,
                    "tickers_total": total_tickers,
                    "trades_so_far": len(all_trades),
                    "pnl_so_far": sum(all_pnl) if all_pnl else 0.0,
                })

        self.logger.info(
            f"Backtest complete: {len(all_trades)} trades | "
            f"Signals evaluated: {signals_evaluated} | "
            f"Signals skipped (no signal): {signals_skipped}"
        )

        return self._compute_result(strategy.name, all_trades, all_pnl)

    def _estimate_vwap_slippage(self, snap: MarketSnapshot, size: int) -> int:
        """
        VWAP-based slippage model.

        Instead of fixed slippage, estimate price impact based on volume.
        From the research: VWAP captures actual achievable prices by accounting
        for order book depth. Higher volume = less slippage.

        Returns slippage in cents.
        """
        if snap.volume <= 0:
            return 3  # high slippage for illiquid markets
        # Impact proportional to trade size relative to market volume
        impact_ratio = size / max(snap.volume, 1)
        # Base slippage 0.5c for liquid markets, scales up with impact
        slippage = 0.5 + impact_ratio * 10.0
        return max(1, min(int(round(slippage)), 5))

    @staticmethod
    def _parse_close_time(close_time_str: str) -> int:
        """Parse ISO close_time string to unix timestamp. Returns 0 if unparseable."""
        if not close_time_str:
            return 0
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(close_time_str)
            return int(dt.timestamp())
        except (ValueError, TypeError):
            return 0

    def _run_single_ticker(
        self,
        strategy: BaseStrategy,
        snapshots: List[MarketSnapshot],
        signals_fn: Callable[[int], ExternalSignals],
        slippage: int,
    ) -> tuple:
        open_position = None
        trade_log = []
        pnl_series = []
        signals_evaluated = 0
        signals_skipped = 0

        for snap in snapshots:
            signals = signals_fn(snap.timestamp)

            # --- Try to close open position ---
            if open_position is not None:
                closed = False
                close_reason = ""

                # 1. Explicit settlement
                if snap.settled is not None:
                    exit_price = 99 if snap.settled else 1
                    close_reason = f"settled={'YES' if snap.settled else 'NO'}"
                    closed = True

                # 2. close_time passed — simulate settlement using mid_price as probability
                elif snap.close_time:
                    close_ts = self._parse_close_time(snap.close_time)
                    if close_ts > 0 and snap.timestamp >= close_ts and snap.mid_price is not None:
                        # Use deterministic pseudo-random based on ticker to simulate
                        # settlement outcome. mid_price/100 = probability of YES winning.
                        yes_prob = snap.mid_price / 100.0
                        seed = hashlib.md5(open_position["ticker"].encode()).hexdigest()
                        rand_val = int(seed[:8], 16) / 0xFFFFFFFF
                        settled_yes = rand_val < yes_prob
                        exit_price = 99 if settled_yes else 1
                        close_reason = f"simulated settle={'YES' if settled_yes else 'NO'}"
                        closed = True

                # 3. Strategy early exit (passes current_ts for backtesting)
                elif snap.mid_price is not None:
                    if strategy.on_exit(
                        open_position["entry_price"],
                        open_position["entry_bar"],
                        open_position["direction"],
                        snap,
                        signals,
                        current_ts=snap.timestamp,
                    ):
                        exit_price = int(snap.mid_price)
                        close_reason = "strategy exit"
                        closed = True

                if closed:
                    entry = open_position["entry_price"]
                    if open_position["direction"] == "yes":
                        pnl = open_position["size"] * ((exit_price - entry) / 100.0)
                    else:
                        no_exit_price = 100 - exit_price
                        pnl = open_position["size"] * ((no_exit_price - entry) / 100.0)

                    hold_secs = snap.timestamp - open_position["entry_bar"]
                    trade_log.append({
                        "ticker": open_position["ticker"],
                        "direction": open_position["direction"],
                        "entry_price": entry,
                        "exit_price": exit_price,
                        "pnl": pnl,
                        "hold_bars": hold_secs,
                        "close_reason": close_reason,
                    })
                    pnl_series.append(pnl)

                    self.logger.debug(
                        f"    CLOSE {open_position['ticker']} "
                        f"{open_position['direction'].upper()} "
                        f"entry={entry}c exit={exit_price}c "
                        f"pnl=${pnl:.2f} ({close_reason}) "
                        f"held {hold_secs // 3600}h{(hold_secs % 3600) // 60}m"
                    )
                    open_position = None
                    continue

            # --- Try to open new position ---
            if open_position is None:
                signal = strategy.on_market_update(snap, signals)
                signals_evaluated += 1
                if signal is not None and snap.mid_price is not None:
                    effective_slippage = (
                        self._estimate_vwap_slippage(snap, signal.size)
                        if self.vwap_slippage else slippage
                    )
                    if signal.direction == "yes" and snap.yes_ask is not None:
                        entry_price = snap.yes_ask + effective_slippage
                    elif signal.direction == "no":
                        # Use no_ask if available, fall back to effective_no_ask
                        no_ask = snap.no_ask if snap.no_ask is not None else snap.effective_no_ask
                        if no_ask is None:
                            continue
                        entry_price = no_ask + effective_slippage
                    else:
                        continue
                    # Skip entries with out-of-bounds prices (bad data)
                    if entry_price <= 1 or entry_price >= 99:
                        continue
                    open_position = {
                        "ticker": snap.ticker,
                        "direction": signal.direction,
                        "entry_price": entry_price,
                        "size": signal.size,
                        "entry_bar": snap.timestamp,
                    }
                    self.logger.debug(
                        f"    OPEN {snap.ticker} {signal.direction.upper()} "
                        f"@ {entry_price}c (mid={snap.mid_price}c, "
                        f"slippage={effective_slippage}c)"
                    )
                else:
                    signals_skipped += 1

        # Close any remaining open position via simulated settlement
        if open_position is not None and snapshots:
            last_snap = snapshots[-1]
            if last_snap.mid_price is not None:
                yes_prob = last_snap.mid_price / 100.0
                seed = hashlib.md5(open_position["ticker"].encode()).hexdigest()
                rand_val = int(seed[:8], 16) / 0xFFFFFFFF
                settled_yes = rand_val < yes_prob
                exit_price = 99 if settled_yes else 1
                entry = open_position["entry_price"]
                if open_position["direction"] == "yes":
                    pnl = open_position["size"] * ((exit_price - entry) / 100.0)
                else:
                    no_exit_price = 100 - exit_price
                    pnl = open_position["size"] * ((no_exit_price - entry) / 100.0)
                hold_secs = last_snap.timestamp - open_position["entry_bar"]
                trade_log.append({
                    "ticker": open_position["ticker"],
                    "direction": open_position["direction"],
                    "entry_price": entry,
                    "exit_price": exit_price,
                    "pnl": pnl,
                    "hold_bars": hold_secs,
                    "close_reason": f"end-of-data settle={'YES' if settled_yes else 'NO'}",
                })
                pnl_series.append(pnl)

        return trade_log, pnl_series, {"evaluated": signals_evaluated, "skipped": signals_skipped}

    def _compute_result(self, name: str, trade_log: List[Dict], pnl_series: List[float]) -> BacktestResult:
        if not trade_log:
            return BacktestResult(name, 0, 0.0, 0.0, 0.0, 0.0, 0.0, [])

        wins = sum(1 for t in trade_log if t["pnl"] > 0)
        win_rate = wins / len(trade_log)
        total_pnl = sum(t["pnl"] for t in trade_log)
        avg_hold = sum(t["hold_bars"] for t in trade_log) / len(trade_log)

        # Sharpe ratio (annualized assuming ~252 trading days)
        if len(pnl_series) > 1:
            mean = sum(pnl_series) / len(pnl_series)
            n = len(pnl_series)
            variance = sum((x - mean) ** 2 for x in pnl_series) / (n - 1) if n > 1 else 0.0001
            std = math.sqrt(variance) if variance > 0 else 0.0001
            sharpe = (mean / std) * math.sqrt(252)
        else:
            sharpe = 0.0

        # Max drawdown
        peak, max_dd = 0.0, 0.0
        running = 0.0
        for p in pnl_series:
            running += p
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd

        return BacktestResult(name, len(trade_log), win_rate, total_pnl, sharpe, max_dd, avg_hold, trade_log)
