import pytest
from unittest.mock import patch, MagicMock
from kalshi_trader.data.polymarket_client import PolymarketClient


def test_get_probabilities_parses_outcome_prices():
    """get_probabilities returns float YES probability from outcomePrices."""
    client = PolymarketClient()
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [
        {"condition_id": "0xabc", "outcomePrices": '["0.65", "0.35"]'}
    ]
    with patch("kalshi_trader.data.polymarket_client.requests.get", return_value=mock_resp):
        result = client.get_probabilities(["0xabc"])
    assert result == {"0xabc": 0.65}


def test_get_probabilities_handles_list_outcome_prices():
    """outcomePrices can be a list (not just a JSON string)."""
    client = PolymarketClient()
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [
        {"condition_id": "0xdef", "outcomePrices": [0.72, 0.28]}
    ]
    with patch("kalshi_trader.data.polymarket_client.requests.get", return_value=mock_resp):
        result = client.get_probabilities(["0xdef"])
    assert result == {"0xdef": 0.72}


def test_get_probabilities_skips_on_network_error():
    """Network failures are swallowed; that condition ID is absent from result."""
    client = PolymarketClient()
    with patch("kalshi_trader.data.polymarket_client.requests.get", side_effect=Exception("timeout")):
        result = client.get_probabilities(["0xbad"])
    assert result == {}


def test_get_probabilities_multiple_ids():
    """Multiple condition IDs are each fetched and returned."""
    client = PolymarketClient()

    def mock_get(url, params, timeout):
        m = MagicMock()
        m.raise_for_status.return_value = None
        cid = params["condition_id"]
        if cid == "0x111":
            m.json.return_value = [{"condition_id": "0x111", "outcomePrices": '["0.60", "0.40"]'}]
        else:
            m.json.return_value = [{"condition_id": "0x222", "outcomePrices": '["0.30", "0.70"]'}]
        return m

    with patch("kalshi_trader.data.polymarket_client.requests.get", side_effect=mock_get):
        result = client.get_probabilities(["0x111", "0x222"])
    assert result["0x111"] == pytest.approx(0.60)
    assert result["0x222"] == pytest.approx(0.30)
