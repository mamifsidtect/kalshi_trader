import json
import time
import os
from datetime import datetime, timezone
from typing import List, Optional
from kalshi_trader.data.models import MarketSnapshot
from kalshi_trader.config import KalshiConfig
from kalshi_trader.utils.logger import get_logger


class MarketCollector:
    def __init__(self, client, config: KalshiConfig):
        self.client = client
        self.config = config
        self.logger = get_logger(__name__, config.log_level)

    def collect_once(self, category: Optional[str] = None) -> List[MarketSnapshot]:
        snapshots = []
        try:
            markets = self.client.get_markets(category=category)
        except Exception as e:
            self.logger.error(f"Failed to fetch markets: {e}")
            return []

        ts = int(time.time())
        for m in markets:
            try:
                yes_bid = m.get("yes_bid")
                yes_ask = m.get("yes_ask")
                _raw_no_bid = m.get("no_bid")
                no_bid = _raw_no_bid if _raw_no_bid is not None else (100 - yes_ask if yes_ask is not None else None)
                _raw_no_ask = m.get("no_ask")
                no_ask = _raw_no_ask if _raw_no_ask is not None else (100 - yes_bid if yes_bid is not None else None)
                snap = MarketSnapshot(
                    ticker=m["ticker"],
                    timestamp=ts,
                    yes_bid=yes_bid,
                    yes_ask=yes_ask,
                    no_bid=no_bid,
                    no_ask=no_ask,
                    volume=m.get("volume", 0),
                    open_interest=m.get("open_interest", 0),
                    category=m.get("category", ""),
                    title=m.get("title", ""),
                    close_time=m.get("close_time", ""),
                )
                snapshots.append(snap)
            except Exception as e:
                self.logger.warning(f"Failed to build snapshot for {m.get('ticker')}: {e}")

        self._persist(snapshots)
        self.logger.info(f"Collected {len(snapshots)} market snapshots")
        return snapshots

    def _persist(self, snapshots: List[MarketSnapshot]):
        import tempfile
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for snap in snapshots:
            dir_path = os.path.join(self.config.data_dir, date_str, snap.ticker)
            os.makedirs(dir_path, exist_ok=True)
            filename = f"{time.time_ns()}.json"
            final_path = os.path.join(dir_path, filename)
            data = json.dumps(snap.to_dict())
            # Atomic write: write to temp file in same directory, then rename
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
            try:
                os.write(fd, data.encode())
            finally:
                os.close(fd)
            os.replace(tmp_path, final_path)

    def load_snapshots(self, ticker: str, date_str: str) -> List[MarketSnapshot]:
        dir_path = os.path.join(self.config.data_dir, date_str, ticker)
        if not os.path.exists(dir_path):
            return []
        snapshots = []
        for fname in sorted(os.listdir(dir_path)):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(dir_path, fname)) as f:
                d = json.load(f)
            snapshots.append(MarketSnapshot(
                ticker=d["ticker"], timestamp=d["timestamp"],
                yes_bid=d["yes_bid"], yes_ask=d["yes_ask"],
                no_bid=d["no_bid"], no_ask=d["no_ask"],
                volume=d["volume"], open_interest=d["open_interest"],
                category=d["category"], title=d.get("title", ""),
                close_time=d.get("close_time", ""), settled=d.get("settled"),
            ))
        return snapshots
