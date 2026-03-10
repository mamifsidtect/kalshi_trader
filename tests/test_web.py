import pytest
from httpx import AsyncClient, ASGITransport
from kalshi_trader.web.app import create_app
from kalshi_trader.config import KalshiConfig


@pytest.fixture
def app():
    cfg = KalshiConfig()
    return create_app(cfg)


@pytest.mark.asyncio
async def test_dashboard_returns_200(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_positions_returns_json(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/positions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_api_signals_returns_json(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/signals")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_research_backtest_endpoint(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/v1/research/backtest", json={
            "strategy": "MarketMaker", "days": 7
        })
    assert resp.status_code in (200, 422)


def test_data_service_get_live_mid_price():
    from unittest.mock import MagicMock
    from kalshi_trader.web.services.data_service import DataService
    from kalshi_trader.config import KalshiConfig

    cfg = KalshiConfig()
    svc = DataService(cfg)
    mock_client = MagicMock()
    mock_client.get_orderbook.return_value = {
        "yes": [[45, 10], [44, 5]],  # best yes bid = 45
        "no":  [[55, 10], [54, 5]],  # best no bid = 55 → yes ask = 100 - 55 = 45
    }
    mid = svc.get_live_mid_price(mock_client, "TEST-1")
    # best yes bid=45, yes ask = 100 - best no bid(55) = 45 → mid = (45+45)/2 = 45.0
    assert mid == 45.0
