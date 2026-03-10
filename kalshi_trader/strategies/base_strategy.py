import time as _time
from abc import ABC, abstractmethod
from typing import Optional
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals, Signal


class BaseStrategy(ABC):
    name: str = "BaseStrategy"
    enabled: bool = True
    exit_profit_cents: int = 0
    exit_time_hours: int = 0

    @abstractmethod
    def on_market_update(
        self,
        market: MarketSnapshot,
        signals: ExternalSignals,
    ) -> Optional[Signal]:
        """Return a Signal to act on this market, or None to skip."""
        ...

    def on_exit(
        self,
        entry_price: Optional[int],
        entry_ts: Optional[int],
        direction: str,
        market: MarketSnapshot,
        signals: ExternalSignals,
    ) -> bool:
        """Return True to close this position early. Checks profit target and time limit."""
        if self.exit_profit_cents > 0 and entry_price is not None and market.mid_price is not None:
            if direction == "yes":
                profit = market.mid_price - entry_price
            elif direction == "no":
                profit = entry_price - market.mid_price
            else:
                profit = None
            if profit is not None and profit >= self.exit_profit_cents:
                return True
        if self.exit_time_hours > 0 and entry_ts is not None:
            elapsed_hours = (_time.time() - entry_ts) / 3600
            if elapsed_hours >= self.exit_time_hours:
                return True
        return False
