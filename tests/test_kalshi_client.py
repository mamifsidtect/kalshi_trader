from unittest.mock import MagicMock, patch
from kalshi_trader.client.kalshi_client import KalshiClient
from kalshi_trader.config import KalshiConfig


def make_client():
    cfg = KalshiConfig(kalshi_api_key="test", kalshi_api_key_id="kid")
    return KalshiClient(cfg)


def test_client_initializes():
    client = make_client()
    assert client is not None


def test_get_markets_returns_list():
    client = make_client()
    with patch.object(client, "_api") as mock_api:
        mock_api.get_markets.return_value = MagicMock(markets=[])
        result = client.get_markets()
        assert isinstance(result, list)


def test_get_orderbook_returns_dict():
    client = make_client()
    with patch.object(client, "_api") as mock_api:
        mock_api.get_market_orderbook.return_value = MagicMock(
            orderbook=MagicMock(yes=[], no=[])
        )
        result = client.get_orderbook("INXD-23-B4500")
        assert "yes" in result
        assert "no" in result


def test_place_order_raises_when_api_unavailable():
    import pytest
    client = make_client()
    client._portfolio_api = None
    with pytest.raises(RuntimeError, match="not available"):
        client.place_order("TEST-1", "yes", 45, 1)


def test_retries_on_failure():
    client = make_client()
    call_count = 0

    def flaky(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("transient error")
        return MagicMock(markets=[])

    with patch("kalshi_trader.client.kalshi_client.time.sleep"):
        with patch.object(client, "_api") as mock_api:
            mock_api.get_markets.side_effect = flaky
            result = client.get_markets()
            assert call_count == 3
            assert isinstance(result, list)
