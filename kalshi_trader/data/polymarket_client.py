import json
import requests
from typing import Dict, List


class PolymarketClient:
    GAMMA_API = "https://gamma-api.polymarket.com"

    def get_probabilities(self, condition_ids: List[str]) -> Dict[str, float]:
        """
        Fetch YES probabilities for given Polymarket condition IDs.
        Returns {condition_id: probability} for successful fetches only.
        Failures are silently skipped.
        """
        results = {}
        for cid in condition_ids:
            try:
                resp = requests.get(
                    f"{self.GAMMA_API}/markets",
                    params={"condition_id": cid},
                    timeout=10,
                )
                resp.raise_for_status()
                markets = resp.json()
                if not isinstance(markets, list):
                    markets = [markets]
                for market in markets:
                    prices_raw = market.get("outcomePrices")
                    if prices_raw is None:
                        continue
                    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                    if prices:
                        results[cid] = float(prices[0])
                        break
            except Exception:
                continue
        return results
