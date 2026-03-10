import json
import os
import pytest
from fastapi.testclient import TestClient
from kalshi_trader.config import KalshiConfig
from kalshi_trader.web.app import create_app
from kalshi_trader.web.services.data_explorer_service import DataExplorerService


def _write_snapshot(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


@pytest.fixture
def client(tmp_path):
    cfg = KalshiConfig(data_dir=str(tmp_path))
    # Write one snapshot so there's data to return
    snap = {
        "ticker": "KXTEST-1", "timestamp": 1741392000,
        "yes_bid": 40, "yes_ask": 45, "no_bid": 55, "no_ask": 60,
        "volume": 100, "open_interest": 50, "category": "financial",
        "title": "Test Market", "close_time": "2026-03-15T00:00:00Z",
        "settled": None,
    }
    _write_snapshot(str(tmp_path / "2026-03-08" / "KXTEST-1" / "1741392000000000000.json"), snap)
    app = create_app(cfg)
    return TestClient(app)


def test_api_markets_returns_list(client):
    resp = client.get("/api/v1/data-explorer/markets")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["ticker"] == "KXTEST-1"


def test_api_market_snapshots_returns_list(client):
    resp = client.get("/api/v1/data-explorer/market/KXTEST-1")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["timestamp"] == 1741392000


def test_api_market_snapshots_404_for_unknown(client):
    resp = client.get("/api/v1/data-explorer/market/NONEXISTENT")
    assert resp.status_code == 404


def test_page_data_explorer_returns_html(client):
    resp = client.get("/data-explorer")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_page_data_explorer_market_returns_html(client):
    resp = client.get("/data-explorer/KXTEST-1")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
