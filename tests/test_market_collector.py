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
