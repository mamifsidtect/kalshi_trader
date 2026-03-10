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


def test_cache_is_loadable_after_write(tmp_path):
    """Cached signals must be readable back via load_cached."""
    from unittest.mock import patch
    cfg = KalshiConfig(data_dir=str(tmp_path))
    collector = ExternalSignalCollector(cfg)
    with patch.object(collector, "_fetch_economic_releases", return_value=[{"id": "CPI"}]):
        with patch.object(collector, "_fetch_news", return_value=[]):
            with patch.object(collector, "_fetch_polls", return_value=[]):
                collector.collect()
    loaded = collector.load_cached()
    assert loaded is not None
    assert loaded.economic_releases == [{"id": "CPI"}]


def test_external_signals_has_correlated_prices_field():
    """ExternalSignals must have a correlated_prices dict field."""
    from kalshi_trader.data.models import ExternalSignals
    sig = ExternalSignals(timestamp=12345)
    assert hasattr(sig, "correlated_prices")
    assert isinstance(sig.correlated_prices, dict)
    # Can be populated
    sig.correlated_prices["KXTEST-1"] = 0.65
    assert sig.correlated_prices["KXTEST-1"] == 0.65
