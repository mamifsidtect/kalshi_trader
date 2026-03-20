import json, logging, os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from kalshi_trader.config import KalshiConfig
from kalshi_trader.data.models import MarketSnapshot
from kalshi_trader.data.market_collector import MarketCollector

_log = logging.getLogger(__name__)


class DataService:
    def __init__(self, config: KalshiConfig, paper_trader=None, signal_feed=None):
        self.config = config
        self._paper_trader = paper_trader
        self._signal_feed = signal_feed or []

    def get_positions(self) -> List[Dict]:
        if self._paper_trader:
            return self._paper_trader.get_positions()
        return []

    def get_order_log(self) -> List[Dict]:
        path = os.path.join(self.config.data_dir, "paper_orders.json")
        if not os.path.exists(path):
            return []
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

    def get_signals(self) -> List[Dict]:
        return list(self._signal_feed)[-50:] if self._signal_feed else []

    def get_summary(self) -> Dict[str, Any]:
        positions = self.get_positions()
        orders = self.get_order_log()
        closed = [o for o in orders if o.get("status") == "closed"]
        wins = sum(1 for o in closed if o.get("pnl", 0) > 0)
        total_pnl = sum(o.get("pnl", 0) for o in closed)
        return {
            "open_positions": len(positions),
            "total_trades": len(closed),
            "win_rate": wins / len(closed) if closed else 0.0,
            "total_pnl": total_pnl,
            "execution_mode": self.config.execution_mode,
        }

    def get_recent_snapshots(self, days: int = 7) -> List[MarketSnapshot]:
        snapshots = []
        collector = MarketCollector(None, self.config)
        data_dir = self.config.data_dir

        # Collect all available date directories, sorted descending
        available_dates = []
        if os.path.exists(data_dir):
            for entry in os.listdir(data_dir):
                if os.path.isdir(os.path.join(data_dir, entry)):
                    available_dates.append(entry)
        available_dates.sort(reverse=True)

        # Use the most recent N days of actual data (not calendar days)
        dates_to_load = available_dates[:days]

        for date in dates_to_load:
            date_dir = os.path.join(data_dir, date)
            for ticker in os.listdir(date_dir):
                ticker_snaps = collector.load_snapshots(ticker, date)
                # Filter out snapshots with no usable price data
                for s in ticker_snaps:
                    if s.mid_price is not None and s.mid_price > 0:
                        snapshots.append(s)
        return snapshots

    def get_markets(self, category: Optional[str] = None) -> List[Dict]:
        snapshots = self.get_recent_snapshots(days=1)
        seen: Dict[str, Dict] = {}
        for s in snapshots:
            if s.ticker not in seen:
                seen[s.ticker] = s.to_dict()
        markets = list(seen.values())
        if category:
            markets = [m for m in markets if m.get("category") == category]
        return markets

    def get_live_mid_price(self, client, ticker: str) -> Optional[float]:
        """
        Fetch live orderbook and return best-bid/best-ask mid price.
        Returns None if orderbook is unavailable or empty.
        """
        try:
            ob = client.get_orderbook(ticker)
            yes_levels = ob.get("yes", [])
            no_levels = ob.get("no", [])
            best_yes_bid = yes_levels[0][0] if yes_levels else None
            best_no_bid = no_levels[0][0] if no_levels else None
            # yes_ask = 100 - best_no_bid (Kalshi binary complement)
            yes_ask = (100 - best_no_bid) if best_no_bid is not None else None
            if best_yes_bid is not None and yes_ask is not None:
                return (best_yes_bid + yes_ask) / 2.0
            return None
        except Exception as e:
            _log.debug(f"get_live_mid_price failed for {ticker}: {e}")
            return None
