"""
Bregman divergence-based directional strategy.

Uses KL-divergence to measure the information-theoretic distance between
the market's implied probability and a fair-value estimate derived from
external signals. Trades when divergence exceeds a threshold.

From the research: "finding the optimal arbitrage trade is equivalent to
computing the Bregman projection." The divergence D(mu||theta) gives the
maximum extractable profit.

For LMSR, the Bregman divergence reduces to KL-divergence:
  D(p||q) = p*ln(p/q) + (1-p)*ln((1-p)/(1-q))

We estimate fair value from external signals (news, polls, correlated prices)
and trade when the market deviates significantly.
"""
import math
from typing import Optional, Tuple
from kalshi_trader.strategies.base_strategy import BaseStrategy
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals, Signal
import time

# Clamp probabilities away from 0/1 to avoid log(0)
_EPS = 1e-6


def kl_divergence(p: float, q: float) -> float:
    """Binary KL-divergence D(p||q) for probabilities in (0,1)."""
    p = max(_EPS, min(1 - _EPS, p))
    q = max(_EPS, min(1 - _EPS, q))
    return p * math.log(p / q) + (1 - p) * math.log((1 - p) / (1 - q))


def estimate_fair_value(market: MarketSnapshot, signals: ExternalSignals) -> Tuple[Optional[float], str]:
    """
    Estimate fair probability from available signal sources.
    Returns (probability, reason_string) or (None, reason) if insufficient data.

    Signal weighting:
    - Correlated external price (e.g. CME implied): weight 0.50
    - Poll data: weight 0.25
    - News sentiment (presence-based proxy): weight 0.15
    - Market mid-price prior: weight 0.10
    """
    weights = []
    estimates = []
    sources = []

    # Correlated prices (strongest signal)
    if signals.correlated_prices and market.ticker in signals.correlated_prices:
        ext_prob = signals.correlated_prices[market.ticker]
        weights.append(0.50)
        estimates.append(ext_prob)
        sources.append(f"ext={ext_prob:.2f}")

    # Poll data — use as probability if available
    if signals.poll_data:
        # Average poll values as rough probability estimate
        poll_vals = [p.get("value", p.get("probability", 0.5)) for p in signals.poll_data]
        if poll_vals:
            poll_avg = sum(poll_vals) / len(poll_vals)
            # Normalize to [0,1] if needed (polls might be percentages)
            if poll_avg > 1:
                poll_avg = poll_avg / 100.0
            weights.append(0.25)
            estimates.append(max(_EPS, min(1 - _EPS, poll_avg)))
            sources.append(f"polls={poll_avg:.2f}")

    # News presence — mild push toward extremes (news = conviction)
    if signals.news_headlines:
        if market.mid_price is not None:
            # News reinforces current direction
            mid_prob = market.mid_price / 100.0
            news_est = mid_prob + (mid_prob - 0.5) * 0.2  # amplify by 20%
            news_est = max(_EPS, min(1 - _EPS, news_est))
            weights.append(0.15)
            estimates.append(news_est)
            sources.append("news_amplify")

    # Market prior (always available if mid_price exists)
    if market.mid_price is not None:
        mid_prob = max(_EPS, min(1 - _EPS, market.mid_price / 100.0))
        weights.append(0.10)
        estimates.append(mid_prob)
        sources.append(f"mid={mid_prob:.2f}")

    if not weights:
        return None, "no_signals"

    # Weighted average
    total_w = sum(weights)
    fair = sum(w * e for w, e in zip(weights, estimates)) / total_w
    return max(_EPS, min(1 - _EPS, fair)), "+".join(sources)


class BregmanDivergenceStrategy(BaseStrategy):
    name = "BregmanDivergence"

    def __init__(
        self,
        min_divergence: float = 0.05,
        contracts: int = 1,
        exit_profit_cents: int = 0,
        exit_time_hours: int = 0,
    ):
        self.min_divergence = min_divergence
        self.contracts = contracts
        self.exit_profit_cents = exit_profit_cents
        self.exit_time_hours = exit_time_hours

    def on_market_update(self, market: MarketSnapshot, signals: ExternalSignals) -> Optional[Signal]:
        if market.mid_price is None:
            return None

        market_prob = max(_EPS, min(1 - _EPS, market.mid_price / 100.0))

        fair_value, sources = estimate_fair_value(market, signals)
        if fair_value is None:
            return None

        # KL-divergence: D(fair || market)
        # Measures how much information the market is "missing"
        div = kl_divergence(fair_value, market_prob)

        if div < self.min_divergence:
            return None

        # Trade toward fair value
        if fair_value > market_prob:
            direction = "yes"
        else:
            direction = "no"

        # Confidence proportional to divergence (capped)
        confidence = min(div * 5.0, 1.0)

        return Signal(
            ticker=market.ticker,
            direction=direction,
            confidence=confidence,
            size=self.contracts,
            strategy_name=self.name,
            reason=f"KL={div:.4f} fair={fair_value:.2f} market={market_prob:.2f} [{sources}]",
            timestamp=int(time.time()),
        )
