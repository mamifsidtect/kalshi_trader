from typing import Dict, Tuple
from kalshi_trader.config import KalshiConfig
from kalshi_trader.data.models import Signal
from kalshi_trader.utils.logger import get_logger


class RiskManager:
    def __init__(self, config: KalshiConfig, bankroll: float):
        self.config = config
        self.bankroll = bankroll
        self.logger = get_logger(__name__, config.log_level)
        self._daily_loss: float = 0.0
        self._halted: bool = False
        self._open_positions: Dict[str, float] = {}  # ticker -> exposure in dollars

    def validate(self, signal: Signal, current_price: int) -> Tuple[bool, str]:
        if self._halted:
            return False, "trading halted: daily loss limit reached"

        if self._daily_loss >= self.bankroll * self.config.daily_loss_limit_pct:
            self._halted = True
            return False, f"daily loss limit reached (${self._daily_loss:.2f})"

        total_exposure = sum(self._open_positions.values())
        max_exposure = self.bankroll * self.config.max_total_exposure_pct
        if total_exposure >= max_exposure:
            return False, f"max total exposure reached (${total_exposure:.2f} >= ${max_exposure:.2f})"

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

    def record_open_position(self, ticker: str, exposure: float):
        self._open_positions[ticker] = exposure

    def close_position(self, ticker: str):
        self._open_positions.pop(ticker, None)

    def reset_daily(self):
        self._daily_loss = 0.0
        self._halted = False
        self.logger.info("Daily risk counters reset")
