import json
import os
import pytest
from kalshi_trader.config import KalshiConfig
from kalshi_trader.web.services.data_explorer_service import DataExplorerService


def _write_snapshot(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _snap(ticker="KXTEST-1", ts=1741564800, yes_bid=40, yes_ask=45,
          volume=100, oi=50, category="financial", title="Test Market",
          settled=None):
    return {
        "ticker": ticker,
        "timestamp": ts,
        "yes_bid": yes_bid, "yes_ask": yes_ask,
        "no_bid": 55, "no_ask": 60,
        "volume": volume, "open_interest": oi,
        "category": category, "title": title,
        "close_time": "2026-03-15T00:00:00Z",
        "settled": settled,
    }


def test_get_all_markets_empty_when_no_data(tmp_path):
    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    assert svc.get_all_markets() == []


def test_get_all_markets_aggregates_by_ticker(tmp_path):
    # Write 3 snapshots for one ticker across 2 dates
    for date, ts in [
        ("2026-03-08", 1741392000),
        ("2026-03-08", 1741392060),
        ("2026-03-09", 1741478400),
    ]:
        path = str(tmp_path / date / "KXTEST-1" / f"{ts}000000000.json")
        _write_snapshot(path, _snap(ts=ts))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    markets = svc.get_all_markets()

    assert len(markets) == 1
    m = markets[0]
    assert m["ticker"] == "KXTEST-1"
    assert m["snapshot_count"] == 3
    assert m["days_covered"] == 2
    assert m["category"] == "financial"


def test_get_all_markets_sparse_flag(tmp_path):
    # Only 50 snapshots — below threshold of 100
    date = "2026-03-08"
    for i in range(50):
        ts = 1741392000 + i * 60
        path = str(tmp_path / date / "KXTEST-1" / f"{ts}000000000.json")
        _write_snapshot(path, _snap(ts=ts))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    markets = svc.get_all_markets()
    assert markets[0]["is_sparse"] is True


def test_get_all_markets_not_sparse_at_100(tmp_path):
    date = "2026-03-08"
    for i in range(100):
        ts = 1741392000 + i * 60
        path = str(tmp_path / date / "KXTEST-1" / f"{ts}000000000.json")
        _write_snapshot(path, _snap(ts=ts))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    markets = svc.get_all_markets()
    assert markets[0]["is_sparse"] is False


def test_get_all_markets_sparkline_excludes_nulls(tmp_path):
    date = "2026-03-08"
    snaps = [
        _snap(ts=1741392000, yes_bid=None, yes_ask=None),  # mid_price = None
        _snap(ts=1741392060, yes_bid=40, yes_ask=45),       # mid_price = 42.5
        _snap(ts=1741392120, yes_bid=42, yes_ask=47),       # mid_price = 44.5
    ]
    for s in snaps:
        path = str(tmp_path / date / "KXTEST-1" / f"{s['timestamp']}000000000.json")
        _write_snapshot(path, s)

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    markets = svc.get_all_markets()
    sparkline = markets[0]["sparkline"]
    assert None not in sparkline
    assert len(sparkline) == 2
    assert sparkline[0] == pytest.approx(42.5)


def test_get_all_markets_sparkline_max_20(tmp_path):
    date = "2026-03-08"
    for i in range(25):
        ts = 1741392000 + i * 60
        path = str(tmp_path / date / "KXTEST-1" / f"{ts}000000000.json")
        _write_snapshot(path, _snap(ts=ts, yes_bid=40 + i, yes_ask=45 + i))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    markets = svc.get_all_markets()
    assert len(markets[0]["sparkline"]) == 20


def test_get_market_snapshots_returns_sorted(tmp_path):
    date = "2026-03-08"
    timestamps = [1741392120, 1741392000, 1741392060]  # out of order
    for ts in timestamps:
        path = str(tmp_path / date / "KXTEST-1" / f"{ts}000000000.json")
        _write_snapshot(path, _snap(ts=ts))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    snaps = svc.get_market_snapshots("KXTEST-1")

    assert len(snaps) == 3
    assert snaps[0]["timestamp"] < snaps[1]["timestamp"] < snaps[2]["timestamp"]


def test_get_market_snapshots_computes_spread(tmp_path):
    date = "2026-03-08"
    path = str(tmp_path / date / "KXTEST-1" / "1741392000000000000.json")
    _write_snapshot(path, _snap(ts=1741392000, yes_bid=40, yes_ask=48))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    snaps = svc.get_market_snapshots("KXTEST-1")
    assert snaps[0]["spread"] == 8  # int: yes_ask - yes_bid = 48 - 40
    assert isinstance(snaps[0]["spread"], int)


def test_get_all_markets_sparkline_empty_when_all_nulls(tmp_path):
    """Sparkline is [] when all snapshots have null mid_price."""
    date = "2026-03-08"
    for i in range(3):
        ts = 1741392000 + i * 60
        path = str(tmp_path / date / "KXTEST-1" / f"{ts}000000000.json")
        _write_snapshot(path, _snap(ts=ts, yes_bid=None, yes_ask=None))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    markets = svc.get_all_markets()
    assert markets[0]["sparkline"] == []


def test_get_market_snapshots_404_unknown_ticker(tmp_path):
    from fastapi import HTTPException
    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    with pytest.raises(HTTPException) as exc:
        svc.get_market_snapshots("NONEXISTENT")
    assert exc.value.status_code == 404


def test_get_market_snapshots_empty_folder_returns_empty(tmp_path):
    # Create the ticker directory but no snapshot files
    ticker_dir = tmp_path / "2026-03-08" / "KXTEST-1"
    ticker_dir.mkdir(parents=True)

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    snaps = svc.get_market_snapshots("KXTEST-1")
    assert snaps == []


def test_get_market_snapshots_skips_malformed_json(tmp_path):
    date = "2026-03-08"
    good_path = str(tmp_path / date / "KXTEST-1" / "1741392000000000000.json")
    bad_path = str(tmp_path / date / "KXTEST-1" / "1741392060000000000.json")
    _write_snapshot(good_path, _snap(ts=1741392000))
    os.makedirs(os.path.dirname(bad_path), exist_ok=True)
    with open(bad_path, "w") as f:
        f.write("{{not valid json")

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    snaps = svc.get_market_snapshots("KXTEST-1")
    assert len(snaps) == 1  # bad file skipped, good file returned
