from typing import Optional
from kalshi_trader.strategies.base_strategy import BaseStrategy
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals, Signal
import time


class MarketMakerStrategy(BaseStrategy):
    name = "MarketMaker"

    def __init__(self, min_spread: int = 3, min_volume: int = 100, contracts_per_quote: int = 1,
                 exit_profit_cents: int = 0, exit_time_hours: int = 0):
        self.min_spread = min_spread
        self.min_volume = min_volume
        self.contracts_per_quote = contracts_per_quote
        self.exit_profit_cents = exit_profit_cents
        self.exit_time_hours = exit_time_hours

    def on_market_update(self, market: MarketSnapshot, signals: ExternalSignals) -> Optional[Signal]:
        if market.spread is None or market.spread < self.min_spread:
            return None
        if market.volume < self.min_volume:
            return None
        yes_bid = market.yes_bid
        no_bid = market.effective_no_bid
        if yes_bid is not None and no_bid is not None and yes_bid < no_bid:
            direction = "yes"
        else:
            direction = "no"
        return Signal(
            ticker=market.ticker,
            direction=direction,
            confidence=min(market.spread / 10.0, 1.0),
            size=self.contracts_per_quote,
            strategy_name=self.name,
            reason=f"spread={market.spread} > min={self.min_spread}",
            timestamp=int(time.time()),
        )
