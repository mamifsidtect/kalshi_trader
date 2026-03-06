from typing import Optional
from kalshi_trader.strategies.base_strategy import BaseStrategy
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals, Signal
import time


class MarketMakerStrategy(BaseStrategy):
    name = "MarketMaker"

    def __init__(self, min_spread: int = 3, min_volume: int = 100, contracts_per_quote: int = 1):
        self.min_spread = min_spread
        self.min_volume = min_volume
        self.contracts_per_quote = contracts_per_quote

    def on_market_update(self, market: MarketSnapshot, signals: ExternalSignals) -> Optional[Signal]:
        if market.spread is None or market.spread < self.min_spread:
            return None
        if market.volume < self.min_volume:
            return None
        # Quote the cheaper side (more room to profit)
        direction = "yes" if market.yes_bid < market.no_bid else "no"
        return Signal(
            ticker=market.ticker,
            direction=direction,
            confidence=min(market.spread / 10.0, 1.0),
            size=self.contracts_per_quote,
            strategy_name=self.name,
            reason=f"spread={market.spread} > min={self.min_spread}",
            timestamp=int(time.time()),
        )
