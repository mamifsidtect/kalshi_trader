from typing import Optional
from kalshi_trader.strategies.base_strategy import BaseStrategy
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals, Signal
import time


class DirectionalStrategy(BaseStrategy):
    name = "Directional"

    def __init__(self, confidence_threshold: float = 0.6, contracts: int = 1,
                 exit_profit_cents: int = 0, exit_time_hours: int = 0):
        self.confidence_threshold = confidence_threshold
        self.contracts = contracts
        self.exit_profit_cents = exit_profit_cents
        self.exit_time_hours = exit_time_hours

    def on_market_update(self, market: MarketSnapshot, signals: ExternalSignals) -> Optional[Signal]:
        confidence, direction, reason = self._score(market, signals)
        if confidence < self.confidence_threshold:
            return None
        return Signal(
            ticker=market.ticker,
            direction=direction,
            confidence=confidence,
            size=self.contracts,
            strategy_name=self.name,
            reason=reason,
            timestamp=int(time.time()),
        )

    def _score(self, market: MarketSnapshot, signals: ExternalSignals):
        """
        Combine signal sources into a directional confidence score.
        Returns (confidence, direction, reason).
        """
        score = 0.0
        sources = []

        if signals.news_headlines:
            score += 0.1
            sources.append("news")

        if signals.economic_releases:
            score -= 0.1
            sources.append("econ_release_penalty")

        if signals.poll_data:
            score += 0.15
            sources.append("polls")

        direction = "yes"  # default direction when price gives no signal
        if market.mid_price is not None and market.mid_price > 60:
            score += 0.2
            direction = "yes"
        elif market.mid_price is not None and market.mid_price < 40:
            score += 0.2
            direction = "no"
        # mid_price in [40, 60] or None: no price signal, direction stays "yes"

        confidence = max(0.0, min(score, 1.0))
        return confidence, direction, f"sources={sources}"
