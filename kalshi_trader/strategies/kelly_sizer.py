"""
Modified Kelly Criterion position sizing.

From the research: position sizing uses a modified Kelly formula accounting
for execution risk:

    f* = (b*p - q) / b * sqrt(p)

Where:
    b = expected profit ratio (edge / cost)
    p = probability of full execution (from order book depth)
    q = 1 - p

The sqrt(p) factor is a conservative adjustment that reduces sizing
when execution probability is uncertain — a half-Kelly variant that
accounts for non-atomic fill risk on CLOBs.

Usage: call kelly_size() from any strategy to get dynamic contract count
instead of using a fixed size.
"""
import math
from kalshi_trader.data.models import MarketSnapshot


def kelly_size(
    edge_cents: float,
    entry_price: int,
    market: MarketSnapshot,
    max_contracts: int = 10,
    execution_prob: float = 0.85,
    bankroll_cents: int = 10000,
    max_bankroll_frac: float = 0.05,
) -> int:
    """
    Compute Kelly-optimal contract count.

    Args:
        edge_cents: Expected profit per contract in cents.
        entry_price: Entry price in cents (1-99).
        market: Current market snapshot (used for volume-based execution estimate).
        max_contracts: Hard cap on position size.
        execution_prob: Base probability of successful fill (0-1).
            Adjusted down when volume is low.
        bankroll_cents: Total capital in cents.
        max_bankroll_frac: Maximum fraction of bankroll per trade.

    Returns:
        Number of contracts (at least 1 if edge > 0, 0 otherwise).
    """
    if edge_cents <= 0 or entry_price <= 0:
        return 0

    # Adjust execution probability based on volume
    # Low volume = harder to fill = lower effective p
    if market.volume > 0:
        vol_factor = min(market.volume / 200.0, 1.0)  # full confidence at 200+ volume
        p = execution_prob * (0.5 + 0.5 * vol_factor)
    else:
        p = execution_prob * 0.5

    q = 1 - p
    b = edge_cents / entry_price  # profit ratio

    if b <= 0:
        return 0

    # Modified Kelly: f = (bp - q) / b * sqrt(p)
    numerator = b * p - q
    if numerator <= 0:
        return 0

    f = (numerator / b) * math.sqrt(p)

    # Convert fraction to contracts
    max_from_bankroll = int((bankroll_cents * max_bankroll_frac) / entry_price)
    contracts = max(1, int(f * max_from_bankroll))

    # Also cap at order book depth (don't move the market)
    depth_cap = max(1, market.volume // 4) if market.volume > 0 else 1

    return min(contracts, max_contracts, depth_cap)
