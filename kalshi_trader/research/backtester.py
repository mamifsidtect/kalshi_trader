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

    def __init__(self, config: KalshiConfig):
        self.config = config
        self.logger = get_logger(__name__, config.log_level)

    def run(
        self,
        strategy: BaseStrategy,
        snapshots: List[MarketSnapshot],
        signals_fn: Callable[[int], ExternalSignals],
        slippage: Optional[int] = None,
    ) -> BacktestResult:
        slippage = slippage if slippage is not None else self.SLIPPAGE_CENTS
        open_position = None
        trade_log = []
        pnl_series = []

        for snap in snapshots:
            signals = signals_fn(snap.timestamp)
            signal = strategy.on_market_update(snap, signals)

            if open_position is None and signal is not None and snap.mid_price is not None:
                entry_price = (
                    snap.yes_ask + slippage if signal.direction == "yes"
                    else snap.no_ask + slippage
                )
                open_position = {
                    "ticker": snap.ticker,
                    "direction": signal.direction,
                    "entry_price": entry_price,
                    "size": signal.size,
                    "entry_bar": snap.timestamp,
                }

            elif open_position is not None:
                # Hold until settled or end of data
                if snap.settled is not None:
                    exit_price = 99 if snap.settled else 1
                    entry = open_position["entry_price"]
                    if open_position["direction"] == "yes":
                        pnl = open_position["size"] * ((exit_price - entry) / 100.0)
                    else:
                        pnl = open_position["size"] * ((entry - exit_price) / 100.0)

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

        return self._compute_result(strategy.name, trade_log, pnl_series)

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
