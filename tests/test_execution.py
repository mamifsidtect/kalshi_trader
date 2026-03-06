import time
from unittest.mock import MagicMock
from kalshi_trader.execution.paper_trader import PaperTrader
from kalshi_trader.data.models import Signal
from kalshi_trader.config import KalshiConfig


def make_signal(ticker="TEST-1"):
    return Signal(
        ticker=ticker, direction="yes", confidence=0.8,
        size=2, strategy_name="test", reason="r",
        timestamp=int(time.time()),
    )


def test_paper_trader_fills_order(tmp_path):
    cfg = KalshiConfig(data_dir=str(tmp_path))
    trader = PaperTrader(cfg, initial_bankroll=1000.0)
    result = trader.execute(make_signal(), current_price=45)
    assert result["status"] == "filled"
    assert result["ticker"] == "TEST-1"


def test_paper_trader_tracks_pnl(tmp_path):
    cfg = KalshiConfig(data_dir=str(tmp_path))
    trader = PaperTrader(cfg, initial_bankroll=1000.0)
    trader.execute(make_signal(), current_price=45)
    positions = trader.get_positions()
    assert len(positions) == 1
    assert positions[0]["ticker"] == "TEST-1"


def test_paper_trader_close_position(tmp_path):
    cfg = KalshiConfig(data_dir=str(tmp_path))
    trader = PaperTrader(cfg, initial_bankroll=1000.0)
    trader.execute(make_signal(), current_price=45)
    trader.close_position("TEST-1", exit_price=70)
    positions = trader.get_positions()
    assert len(positions) == 0
    assert trader.realized_pnl > 0  # bought YES at 45, settled at 70


def test_paper_trader_persists_log(tmp_path):
    cfg = KalshiConfig(data_dir=str(tmp_path))
    trader = PaperTrader(cfg, initial_bankroll=1000.0)
    trader.execute(make_signal(), current_price=45)
    log = trader.get_order_log()
    assert len(log) >= 1
