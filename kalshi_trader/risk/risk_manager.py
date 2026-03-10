from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from kalshi_trader.config import KalshiConfig
from kalshi_trader.data.models import Signal
from kalshi_trader.utils.logger import get_logger


@dataclass
class PositionMeta:
    exposure: float
    category: str = ""
    entry_price: int = 0
    entry_ts: int = 0
    direction: str = "yes"
    strategy_name: str = ""


class RiskManager:
    def __init__(self, config: KalshiConfig, bankroll: float):
        self.config = config
        self.bankroll = bankroll
        self.logger = get_logger(__name__, config.log_level)
        self._daily_loss: float = 0.0
        self._halted: bool = False
        self._open_positions: Dict[str, PositionMeta] = {}

    def validate(self, signal: Signal, current_price: int, category: str = "") -> Tuple[bool, str]:
        if self._halted:
            return False, "trading halted: daily loss limit reached"

        if self._daily_loss >= self.bankroll * self.config.daily_loss_limit_pct:
            self._halted = True
            return False, f"daily loss limit reached (${self._daily_loss:.2f})"

        total_exposure = sum(m.exposure for m in self._open_positions.values())
        max_exposure = self.bankroll * self.config.max_total_exposure_pct
        if total_exposure >= max_exposure:
            return False, f"max total exposure reached (${total_exposure:.2f} >= ${max_exposure:.2f})"

        if category:
            cat_exposure = sum(
                m.exposure for m in self._open_positions.values() if m.category == category
            )
            max_cat = self.bankroll * self.config.max_category_exposure_pct
            if cat_exposure >= max_cat:
                return False, f"category '{category}' exposure limit reached (${cat_exposure:.2f} >= ${max_cat:.2f})"

        return True, "ok"

    def size_position(self, current_price: int) -> int:
        if current_price <= 0:
            return 0
        max_dollars = self.bankroll * self.config.max_position_pct
        cost_per_contract = current_price / 100.0
        return max(1, int(max_dollars / cost_per_contract))

    def record_daily_loss(self, amount: float):
        self._daily_loss += amount
        if self._daily_loss >= self.bankroll * self.config.daily_loss_limit_pct:
            self._halted = True
            self.logger.warning(f"Daily loss limit reached: ${self._daily_loss:.2f}")

    def record_open_position(
        self,
        ticker: str,
        exposure: float,
        category: str = "",
        entry_price: int = 0,
        entry_ts: int = 0,
        direction: str = "yes",
        strategy_name: str = "",
    ):
        self._open_positions[ticker] = PositionMeta(
            exposure=exposure,
            category=category,
            entry_price=entry_price,
            entry_ts=entry_ts,
            direction=direction,
            strategy_name=strategy_name,
        )

    def has_position(self, ticker: str) -> bool:
        return ticker in self._open_positions

    def get_position_meta(self, ticker: str) -> Optional[PositionMeta]:
        return self._open_positions.get(ticker)

    def close_position(self, ticker: str):
        self._open_positions.pop(ticker, None)

    def reset_daily(self):
        self._daily_loss = 0.0
        self._halted = False
        self.logger.info("Daily risk counters reset")
