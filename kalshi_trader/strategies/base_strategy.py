from abc import ABC, abstractmethod
from typing import Optional
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals, Signal


class BaseStrategy(ABC):
    name: str = "BaseStrategy"
    enabled: bool = True

    @abstractmethod
    def on_market_update(
        self,
        market: MarketSnapshot,
        signals: ExternalSignals,
    ) -> Optional[Signal]:
        """Return a Signal to act on this market, or None to skip."""
        ...
