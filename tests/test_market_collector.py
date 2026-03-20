import json, os
from unittest.mock import MagicMock
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals, Signal
from kalshi_trader.data.market_collector import MarketCollector
from kalshi_trader.config import KalshiConfig


def test_market_snapshot_fields():
    snap = MarketSnapshot(
        ticker="INXD-23-B4500", timestamp=1700000000,
        yes_bid=45, yes_ask=47, no_bid=53, no_ask=55,
        volume=1000, open_interest=500, category="financial"
    )
    assert snap.mid_price == 46.0
    assert snap.spread == 2


def test_market_collector_saves_snapshot(tmp_path):
    cfg = KalshiConfig(data_dir=str(tmp_path))
    mock_client = MagicMock()
    mock_client.get_markets.return_value = [{
        "ticker": "TEST-1", "yes_bid": 40, "yes_ask": 42,
        "no_bid": 58, "no_ask": 60, "volume": 100,
        "open_interest": 50, "category": "financial", "status": "open",
        "title": "Test Market", "close_time": "2024-12-31"
    }]
    collector = MarketCollector(mock_client, cfg)
    snapshots = collector.collect_once()
    assert len(snapshots) == 1
    assert snapshots[0].ticker == "TEST-1"


def test_market_collector_derives_no_bid_no_ask(tmp_path):
    """collect_once must derive no_bid and no_ask from YES prices when absent."""
    cfg = KalshiConfig(data_dir=str(tmp_path))
    mock_client = MagicMock()
    mock_client.get_markets.return_value = [{
        "ticker": "TEST-2", "yes_bid": 40, "yes_ask": 45,
        "volume": 100, "open_interest": 50,
        "category": "financial", "title": "T", "close_time": "",
    }]
    collector = MarketCollector(mock_client, cfg)
    snapshots = collector.collect_once()
    assert snapshots[0].no_bid == 55   # 100 - yes_ask(45)
    assert snapshots[0].no_ask == 60   # 100 - yes_bid(40)


def test_collector_persists_to_disk(tmp_path):
    cfg = KalshiConfig(data_dir=str(tmp_path))
    mock_client = MagicMock()
    mock_client.get_markets.return_value = [{
        "ticker": "TEST-1", "yes_bid": 40, "yes_ask": 42,
        "no_bid": 58, "no_ask": 60, "volume": 100,
        "open_interest": 50, "category": "financial", "status": "open",
        "title": "Test Market", "close_time": "2024-12-31"
    }]
    collector = MarketCollector(mock_client, cfg)
    collector.collect_once()
    files = list(tmp_path.rglob("*.json"))
    assert len(files) > 0


def test_backfill_settlement_updates_snapshots(tmp_path):
    """backfill_settlement must update stored snapshots with settlement outcomes."""
    cfg = KalshiConfig()
    cfg.data_dir = str(tmp_path)

    # Create a stored snapshot without settlement
    ticker = "TEST-TICKER"
    date_str = "2026-03-07"
    ticker_dir = tmp_path / date_str / ticker
    ticker_dir.mkdir(parents=True)
    snap_data = {
        "ticker": ticker, "timestamp": 1709856000,
        "yes_bid": 45, "yes_ask": 50, "no_bid": 50, "no_ask": 55,
        "volume": 100, "open_interest": 50, "category": "financial",
        "title": "Test", "close_time": "", "settled": None,
    }
    with open(ticker_dir / "1709856000000000000.json", "w") as f:
        json.dump(snap_data, f)

    # Mock client that returns settled market
    class MockClient:
        def get_markets(self, status=None):
            if status == "settled":
                return [{
                    "ticker": ticker, "result": "yes",
                    "yes_bid": 99, "yes_ask": 100, "no_bid": 0, "no_ask": 1,
                    "volume": 200, "open_interest": 0, "category": "financial",
                    "title": "Test", "close_time": "",
                }]
            return []

    collector = MarketCollector(MockClient(), cfg)
    updated = collector.backfill_settlement(date_str)
    assert updated >= 1

    # Verify the snapshot was updated
    with open(ticker_dir / "1709856000000000000.json") as f:
        data = json.load(f)
    assert data["settled"] is True
