import json, os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from kalshi_trader.config import KalshiConfig
from kalshi_trader.data.models import MarketSnapshot
from kalshi_trader.data.market_collector import MarketCollector


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
        with open(path) as f:
            return json.load(f)

    def get_signals(self) -> List[Dict]:
        return list(self._signal_feed[-50:]) if self._signal_feed else []

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
        for i in range(days):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            date_dir = os.path.join(self.config.data_dir, date)
            if not os.path.exists(date_dir):
                continue
            for ticker in os.listdir(date_dir):
                snapshots.extend(collector.load_snapshots(ticker, date))
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
