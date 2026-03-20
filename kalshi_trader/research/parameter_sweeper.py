"""
Automatic parameter sweep engine.

When a strategy's default parameters fail the promotion gate, the sweeper
exhaustively searches a predefined parameter grid, backtests each combination,
and returns the best configuration (if any passes the gate).
"""
import itertools
from dataclasses import dataclass, field
from typing import List, Dict, Any, Callable, Optional, Type

from kalshi_trader.config import KalshiConfig
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals
from kalshi_trader.research.backtester import Backtester, BacktestResult
from kalshi_trader.strategies.base_strategy import BaseStrategy
from kalshi_trader.strategies.market_maker import MarketMakerStrategy
from kalshi_trader.strategies.directional import DirectionalStrategy
from kalshi_trader.strategies.arbitrage import ArbitrageStrategy
from kalshi_trader.strategies.single_condition_arb import SingleConditionArbStrategy
from kalshi_trader.strategies.bregman_divergence import BregmanDivergenceStrategy
from kalshi_trader.utils.logger import get_logger


@dataclass
class SweepResult:
    strategy_name: str
    params: Dict[str, Any]
    backtest: BacktestResult
    promoted: bool


@dataclass
class SweepReport:
    all_results: List[SweepResult] = field(default_factory=list)
    best: Optional[SweepResult] = None
    total_combinations: int = 0

    @property
    def promoted_results(self) -> List[SweepResult]:
        return [r for r in self.all_results if r.promoted]


# Default parameter grids per strategy
PARAMETER_GRIDS: Dict[str, Dict[str, List]] = {
    "MarketMaker": {
        "min_spread": [1, 2, 3, 4, 5, 7, 10],
        "min_volume": [0, 25, 50, 100, 200],
        "contracts_per_quote": [1],
        "exit_profit_cents": [0, 3, 5, 8],
        "exit_time_hours": [0, 2, 6, 12],
    },
    "Directional": {
        "confidence_threshold": [0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
        "contracts": [1],
        "exit_profit_cents": [0, 3, 5, 8],
        "exit_time_hours": [0, 2, 6, 12],
    },
    "Arbitrage": {
        "min_edge": [0.02, 0.03, 0.05, 0.07, 0.10, 0.15],
        "contracts": [1],
        "exit_profit_cents": [0, 3, 5, 8],
        "exit_time_hours": [0, 2, 6, 12],
    },
    "SingleConditionArb": {
        "min_edge_cents": [2, 3, 5, 7, 10, 15],
        "max_entry_price": [85, 90, 95],
        "contracts": [1],
        "exit_profit_cents": [0, 3, 5, 8],
        "exit_time_hours": [0, 2, 6, 12],
    },
    "BregmanDivergence": {
        "min_divergence": [0.01, 0.02, 0.05, 0.08, 0.10, 0.15, 0.20],
        "contracts": [1],
        "exit_profit_cents": [0, 3, 5, 8],
        "exit_time_hours": [0, 2, 6, 12],
    },
}

STRATEGY_CLASSES: Dict[str, Type[BaseStrategy]] = {
    "MarketMaker": MarketMakerStrategy,
    "Directional": DirectionalStrategy,
    "Arbitrage": ArbitrageStrategy,
    "SingleConditionArb": SingleConditionArbStrategy,
    "BregmanDivergence": BregmanDivergenceStrategy,
}


class ParameterSweeper:
    def __init__(self, config: KalshiConfig):
        self.config = config
        self.logger = get_logger(__name__, config.log_level)

    def sweep(
        self,
        strategy_name: str,
        snapshots: List[MarketSnapshot],
        signals_fn: Callable[[int], ExternalSignals],
        param_grid: Optional[Dict[str, List]] = None,
        rank_by: str = "sharpe",
    ) -> SweepReport:
        """Run a full parameter sweep for one strategy.

        Args:
            strategy_name: Key into STRATEGY_CLASSES / PARAMETER_GRIDS.
            snapshots: Historical market data.
            signals_fn: Function returning ExternalSignals for a given timestamp.
            param_grid: Override the default grid. Keys are constructor kwarg names.
            rank_by: Metric to sort by — "sharpe" or "win_rate".

        Returns:
            SweepReport with all results sorted best-first.
        """
        cls = STRATEGY_CLASSES.get(strategy_name)
        if cls is None:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        grid = param_grid or PARAMETER_GRIDS.get(strategy_name, {})
        if not grid:
            raise ValueError(f"No parameter grid defined for {strategy_name}")

        param_names = list(grid.keys())
        param_values = list(grid.values())
        combos = list(itertools.product(*param_values))

        self.logger.info(
            f"Starting parameter sweep for {strategy_name}: "
            f"{len(combos)} combinations across {len(param_names)} params"
        )

        bt = Backtester(self.config)
        report = SweepReport(total_combinations=len(combos))

        for i, combo in enumerate(combos):
            params = dict(zip(param_names, combo))
            strategy = cls(**params)
            result = bt.run(strategy, snapshots, signals_fn)
            promoted = result.meets_promotion_gate(self.config)

            sr = SweepResult(
                strategy_name=strategy_name,
                params=params,
                backtest=result,
                promoted=promoted,
            )
            report.all_results.append(sr)

            if (i + 1) % 50 == 0:
                self.logger.info(f"  Sweep progress: {i + 1}/{len(combos)}")

        # Sort: promoted first, then by rank_by descending
        report.all_results.sort(
            key=lambda r: (r.promoted, getattr(r.backtest, rank_by, 0)),
            reverse=True,
        )

        if report.all_results and report.all_results[0].promoted:
            report.best = report.all_results[0]

        self._log_summary(report, rank_by)
        return report

    def sweep_all(
        self,
        snapshots: List[MarketSnapshot],
        signals_fn: Callable[[int], ExternalSignals],
        rank_by: str = "sharpe",
    ) -> Dict[str, SweepReport]:
        """Sweep all strategies and return reports keyed by strategy name."""
        reports = {}
        for name in STRATEGY_CLASSES:
            if name not in PARAMETER_GRIDS:
                continue
            reports[name] = self.sweep(name, snapshots, signals_fn, rank_by=rank_by)
        return reports

    def _log_summary(self, report: SweepReport, rank_by: str) -> None:
        promoted = report.promoted_results
        self.logger.info(
            f"Sweep complete: {report.total_combinations} combos tested, "
            f"{len(promoted)} passed promotion gate"
        )
        if report.best:
            b = report.best
            self.logger.info(
                f"  Best config: {b.params}\n"
                f"    Sharpe={b.backtest.sharpe:.2f}  "
                f"Win={b.backtest.win_rate:.1%}  "
                f"PnL=${b.backtest.total_pnl:.2f}  "
                f"Trades={b.backtest.total_trades}  "
                f"MaxDD=${b.backtest.max_drawdown:.2f}"
            )
        else:
            # Show top 3 even if none promoted
            top = report.all_results[:3]
            if top:
                self.logger.info("  No config passed the gate. Top 3:")
                for i, r in enumerate(top, 1):
                    self.logger.info(
                        f"    #{i} {r.params} — "
                        f"Sharpe={r.backtest.sharpe:.2f}  "
                        f"Win={r.backtest.win_rate:.1%}  "
                        f"Trades={r.backtest.total_trades}"
                    )
