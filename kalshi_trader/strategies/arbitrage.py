from typing import Optional, Dict
from kalshi_trader.strategies.base_strategy import BaseStrategy
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals, Signal
import time


class ArbitrageStrategy(BaseStrategy):
    name = "Arbitrage"

    def __init__(self, min_edge: float = 0.05, contracts: int = 1,
                 exit_profit_cents: int = 0, exit_time_hours: int = 0):
        self.min_edge = min_edge
        self.contracts = contracts
        self.exit_profit_cents = exit_profit_cents
        self.exit_time_hours = exit_time_hours
        self._correlated_prices: Dict[str, float] = {}

    def set_correlated_price(self, ticker: str, implied_prob: float):
        """Register an externally-derived probability for a market (e.g., from CME futures)."""
        self._correlated_prices[ticker] = implied_prob

    def on_market_update(self, market: MarketSnapshot, signals: ExternalSignals) -> Optional[Signal]:
        if market.ticker not in self._correlated_prices:
            return None
        if market.mid_price is None:
            return None

        external_prob = self._correlated_prices[market.ticker]
        kalshi_prob = market.mid_price / 100.0
        edge = abs(external_prob - kalshi_prob)

        if edge < self.min_edge:
            return None

        direction = "yes" if external_prob > kalshi_prob else "no"
        return Signal(
            ticker=market.ticker,
            direction=direction,
            confidence=min(edge * 5, 1.0),
            size=self.contracts,
            strategy_name=self.name,
            reason=f"external={external_prob:.2f} kalshi={kalshi_prob:.2f} edge={edge:.2f}",
            timestamp=int(time.time()),
        )
