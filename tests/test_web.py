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
