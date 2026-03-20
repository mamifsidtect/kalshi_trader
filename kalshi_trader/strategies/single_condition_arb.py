"""
Single-condition arbitrage strategy.

Exploits mispricing when YES + NO prices don't sum to $1.00.
From the research: 41% of conditions showed this type of arbitrage,
with median mispricing of $0.60 per dollar.

Buy both sides when yes_ask + no_ask < 100 cents (guaranteed profit on settlement).
Direction chosen as the cheaper side for maximum edge.
"""
from typing import Optional
from kalshi_trader.strategies.base_strategy import BaseStrategy
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals, Signal
import time


class SingleConditionArbStrategy(BaseStrategy):
    name = "SingleConditionArb"

    def __init__(
        self,
        min_edge_cents: int = 5,
        max_entry_price: int = 95,
        contracts: int = 1,
        exit_profit_cents: int = 0,
        exit_time_hours: int = 0,
    ):
        self.min_edge_cents = min_edge_cents
        self.max_entry_price = max_entry_price
        self.contracts = contracts
        self.exit_profit_cents = exit_profit_cents
        self.exit_time_hours = exit_time_hours

    def on_market_update(self, market: MarketSnapshot, signals: ExternalSignals) -> Optional[Signal]:
        if market.yes_ask is None:
            return None
        no_ask = market.no_ask if market.no_ask is not None else market.effective_no_ask
        if no_ask is None:
            return None

        # Cost to buy both sides
        total_cost = market.yes_ask + no_ask
        # On settlement, one side pays 100 cents
        edge = 100 - total_cost

        if edge < self.min_edge_cents:
            return None

        # Buy the cheaper side (higher expected value relative to cost)
        if market.yes_ask <= no_ask:
            direction = "yes"
            entry = market.yes_ask
        else:
            direction = "no"
            entry = no_ask

        if entry > self.max_entry_price:
            return None

        confidence = min(edge / 20.0, 1.0)

        return Signal(
            ticker=market.ticker,
            direction=direction,
            confidence=confidence,
            size=self.contracts,
            strategy_name=self.name,
            reason=f"yes_ask={market.yes_ask}+no_ask={no_ask}={total_cost}<100 edge={edge}c",
            timestamp=int(time.time()),
        )
