from unittest.mock import patch
from kalshi_trader.data.external_signals import ExternalSignalCollector
from kalshi_trader.data.models import ExternalSignals
from kalshi_trader.config import KalshiConfig


def test_collector_returns_signals_object():
    cfg = KalshiConfig()
    collector = ExternalSignalCollector(cfg)
    with patch.object(collector, "_fetch_economic_releases", return_value=[]):
        with patch.object(collector, "_fetch_news", return_value=[]):
            with patch.object(collector, "_fetch_polls", return_value=[]):
                signals = collector.collect()
    assert isinstance(signals, ExternalSignals)


def test_collector_degrades_on_failure():
    cfg = KalshiConfig()
    collector = ExternalSignalCollector(cfg)
    with patch.object(collector, "_fetch_economic_releases", side_effect=Exception("network error")):
        with patch.object(collector, "_fetch_news", return_value=[{"headline": "test"}]):
            with patch.object(collector, "_fetch_polls", return_value=[]):
                signals = collector.collect()
    assert signals.news_headlines == [{"headline": "test"}]
    assert signals.economic_releases == []
