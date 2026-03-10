import json
import logging
import os
from typing import Dict, List, Optional

from fastapi import HTTPException

from kalshi_trader.config import KalshiConfig

_log = logging.getLogger(__name__)


class DataExplorerService:
    SPARSE_THRESHOLD = 100  # snapshots below this = is_sparse=True
    SPARKLINE_MAX = 20

    def __init__(self, config: KalshiConfig):
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all_markets(self) -> List[Dict]:
        """Return a summary dict per distinct ticker found in the data directory."""
        data_dir = self.config.data_dir
        if not os.path.isdir(data_dir):
            return []

        # Collect all snapshot paths grouped by ticker
        ticker_files: Dict[str, List[str]] = {}
        ticker_dates: Dict[str, set] = {}

        for date_entry in sorted(os.scandir(data_dir), key=lambda e: e.name):
            if not date_entry.is_dir():
                continue
            for ticker_entry in os.scandir(date_entry.path):
                if not ticker_entry.is_dir():
                    continue
                ticker = ticker_entry.name
                ticker_files.setdefault(ticker, [])
                ticker_dates.setdefault(ticker, set())
                ticker_dates[ticker].add(date_entry.name)
                for snap_file in os.scandir(ticker_entry.path):
                    if snap_file.name.endswith(".json"):
                        ticker_files[ticker].append(snap_file.path)

        if not ticker_files:
            return []

        results = []
        for ticker, file_paths in ticker_files.items():
            summary = self._build_market_summary(ticker, file_paths, ticker_dates[ticker])
            if summary:
                results.append(summary)

        results.sort(key=lambda m: m["ticker"])
        return results

    def get_market_snapshots(self, ticker: str) -> List[Dict]:
        """
        Return all snapshots for a ticker, sorted ascending by timestamp.
        Raises HTTPException 404 if the ticker is not found in the data directory.
        Skips malformed JSON files (logs a warning).
        """
        data_dir = self.config.data_dir
        file_paths = []
        found = False

        if os.path.isdir(data_dir):
            for date_entry in os.scandir(data_dir):
                if not date_entry.is_dir():
                    continue
                ticker_dir = os.path.join(date_entry.path, ticker)
                if os.path.isdir(ticker_dir):
                    found = True
                    for snap_file in os.scandir(ticker_dir):
                        if snap_file.name.endswith(".json"):
                            file_paths.append(snap_file.path)

        if not found:
            raise HTTPException(status_code=404, detail="Ticker not found")

        snapshots = []
        for path in file_paths:
            snap = self._load_snapshot(path)
            if snap is not None:
                snapshots.append(snap)

        snapshots.sort(key=lambda s: s["timestamp"])
        return snapshots

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_snapshot(self, path: str) -> Optional[Dict]:
        """Load a single snapshot JSON file. Returns None on parse error."""
        try:
            with open(path) as f:
                data = json.load(f)
            yes_bid = data.get("yes_bid")
            yes_ask = data.get("yes_ask")
            mid_price = (yes_bid + yes_ask) / 2.0 if yes_bid is not None and yes_ask is not None else None
            spread = round(yes_ask - yes_bid) if yes_bid is not None and yes_ask is not None else None
            return {
                "timestamp": data.get("timestamp", 0),
                "mid_price": mid_price,
                "spread": spread,
                "volume": data.get("volume", 0),
                "open_interest": data.get("open_interest", 0),
                "settled": data.get("settled"),
            }
        except (json.JSONDecodeError, OSError, TypeError) as e:
            _log.warning(f"Skipping malformed snapshot file {path}: {e}")
            return None

    def _build_market_summary(self, ticker: str, file_paths: List[str], dates: set) -> Optional[Dict]:
        """Build the summary dict for a single ticker from its file paths."""
        if not file_paths:
            return None

        # Load all snapshots to build sparkline and get latest metadata
        snapshots = []
        for path in sorted(file_paths):
            snap_raw = self._load_raw(path)
            if snap_raw is not None:
                snapshots.append(snap_raw)

        if not snapshots:
            return None

        snapshots.sort(key=lambda s: s.get("timestamp", 0))
        latest = snapshots[-1]

        # Build sparkline: last ≤20 non-null mid_price values
        mid_prices = []
        for s in snapshots:
            yb = s.get("yes_bid")
            ya = s.get("yes_ask")
            if yb is not None and ya is not None:
                mid_prices.append((yb + ya) / 2.0)
        sparkline = mid_prices[-self.SPARKLINE_MAX:]

        # Date range string
        sorted_dates = sorted(dates)
        date_range = self._format_date_range(sorted_dates[0], sorted_dates[-1])

        return {
            "ticker": ticker,
            "category": latest.get("category", ""),
            "title": latest.get("title", ticker),
            "snapshot_count": len(file_paths),
            "days_covered": len(dates),
            "date_range": date_range,
            "settled": latest.get("settled"),
            "is_sparse": len(file_paths) < self.SPARSE_THRESHOLD,
            "sparkline": sparkline,
        }

    def _load_raw(self, path: str) -> Optional[Dict]:
        """Load raw JSON without transformation. Returns None on error."""
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _format_date_range(start: str, end: str) -> str:
        """Format 'YYYY-MM-DD' dates as 'Mar 7–10' or 'Feb 28–Mar 3'."""
        from datetime import datetime
        MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
        sm = MONTHS[s.month - 1]
        em = MONTHS[e.month - 1]
        if s == e:
            return f"{sm} {s.day}"
        if s.month == e.month:
            return f"{sm} {s.day}–{e.day}"
        return f"{sm} {s.day}–{em} {e.day}"
