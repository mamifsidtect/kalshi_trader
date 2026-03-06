from typing import List, Dict
from kalshi_trader.data.models import MarketSnapshot
from kalshi_trader.config import KalshiConfig
from kalshi_trader.utils.logger import get_logger


class SignalTester:
    def __init__(self, config: KalshiConfig):
        self.config = config
        self.logger = get_logger(__name__, config.log_level)

    def test_price_momentum(self, snapshots: List[MarketSnapshot]) -> float:
        """
        Test whether mid_price > 50 predicts YES settlement.
        Returns accuracy (fraction correct) over settled snapshots.
        """
        if not snapshots:
            return 0.0
        settled = [s for s in snapshots if s.settled is not None]
        if not settled:
            return 0.0

        correct = 0
        for snap in settled:
            if snap.mid_price is None:
                continue
            predicted_yes = snap.mid_price > 50
            actual_yes = snap.settled
            if predicted_yes == actual_yes:
                correct += 1
        return correct / len(settled)

    def test_spread_liquidity(self, snapshots: List[MarketSnapshot]) -> Dict:
        """
        Analyze spread distribution to find market-making opportunities.
        Returns summary stats.
        """
        spreads = [s.spread for s in snapshots if s.spread is not None]
        if not spreads:
            return {"mean_spread": 0, "pct_tradeable": 0.0, "n_samples": 0}
        mean_spread = sum(spreads) / len(spreads)
        tradeable = sum(1 for sp in spreads if sp >= 3)
        return {
            "mean_spread": mean_spread,
            "pct_tradeable": tradeable / len(spreads),
            "n_samples": len(spreads),
        }
