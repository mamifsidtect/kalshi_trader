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
    ) -> BacktestResult:
        slippage = slippage if slippage is not None else self.SLIPPAGE_CENTS

        # Group snapshots by ticker to avoid cross-ticker contamination
        by_ticker: Dict[str, List[MarketSnapshot]] = {}
        for snap in snapshots:
            by_ticker.setdefault(snap.ticker, []).append(snap)

        all_trades: List[Dict] = []
        all_pnl: List[float] = []

        for ticker_snaps in by_ticker.values():
            trades, pnl = self._run_single_ticker(strategy, ticker_snaps, signals_fn, slippage)
            all_trades.extend(trades)
            all_pnl.extend(pnl)

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

        for snap in snapshots:
            signals = signals_fn(snap.timestamp)

            # --- Try to close open position ---
            if open_position is not None:
                closed = False

                # 1. Explicit settlement
                if snap.settled is not None:
                    exit_price = 99 if snap.settled else 1
                    closed = True

                # 2. close_time passed — infer outcome from last mid_price
                elif snap.close_time:
                    close_ts = self._parse_close_time(snap.close_time)
                    if close_ts > 0 and snap.timestamp >= close_ts and snap.mid_price is not None:
                        exit_price = int(snap.mid_price)
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
                        closed = True

                if closed:
                    entry = open_position["entry_price"]
                    if open_position["direction"] == "yes":
                        pnl = open_position["size"] * ((exit_price - entry) / 100.0)
                    else:
                        no_exit_price = 100 - exit_price
                        pnl = open_position["size"] * ((no_exit_price - entry) / 100.0)

                    trade_log.append({
                        "ticker": open_position["ticker"],
                        "direction": open_position["direction"],
                        "entry_price": entry,
                        "exit_price": exit_price,
                        "pnl": pnl,
                        "hold_bars": snap.timestamp - open_position["entry_bar"],
                    })
                    pnl_series.append(pnl)
                    open_position = None
                    continue

            # --- Try to open new position ---
            if open_position is None:
                signal = strategy.on_market_update(snap, signals)
                if signal is not None and snap.mid_price is not None:
                    effective_slippage = (
                        self._estimate_vwap_slippage(snap, signal.size)
                        if self.vwap_slippage else slippage
                    )
                    if signal.direction == "yes" and snap.yes_ask is not None:
                        entry_price = snap.yes_ask + effective_slippage
                    elif signal.direction == "no" and snap.no_ask is not None:
                        entry_price = snap.no_ask + effective_slippage
                    else:
                        continue
                    open_position = {
                        "ticker": snap.ticker,
                        "direction": signal.direction,
                        "entry_price": entry_price,
                        "size": signal.size,
                        "entry_bar": snap.timestamp,
                    }

        return trade_log, pnl_series

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
