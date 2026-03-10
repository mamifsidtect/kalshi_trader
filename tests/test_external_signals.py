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


def test_collector_populates_correlated_prices_from_mapping(tmp_path):
    """When ticker_mappings_file is set, correlated_prices is populated from Polymarket."""
    import json
    from unittest.mock import patch
    from kalshi_trader.data.polymarket_client import PolymarketClient

    mapping = {"KXTEST-1": "0xabc123"}
    mapping_file = tmp_path / "mappings.json"
    mapping_file.write_text(json.dumps(mapping))

    cfg = KalshiConfig(data_dir=str(tmp_path), ticker_mappings_file=str(mapping_file))
    collector = ExternalSignalCollector(cfg)

    with patch.object(collector, "_fetch_economic_releases", return_value=[]):
        with patch.object(collector, "_fetch_news", return_value=[]):
            with patch.object(collector, "_fetch_polls", return_value=[]):
                with patch.object(PolymarketClient, "get_probabilities", return_value={"0xabc123": 0.72}):
                    signals = collector.collect()

    assert signals.correlated_prices == {"KXTEST-1": 0.72}


def test_collector_skips_correlated_prices_when_no_mapping(tmp_path):
    """When ticker_mappings_file is empty string, correlated_prices is empty."""
    cfg = KalshiConfig(data_dir=str(tmp_path), ticker_mappings_file="")
    collector = ExternalSignalCollector(cfg)
    with patch.object(collector, "_fetch_economic_releases", return_value=[]):
        with patch.object(collector, "_fetch_news", return_value=[]):
            with patch.object(collector, "_fetch_polls", return_value=[]):
                signals = collector.collect()
    assert signals.correlated_prices == {}
