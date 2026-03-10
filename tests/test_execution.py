import time
from unittest.mock import MagicMock
from kalshi_trader.execution.paper_trader import PaperTrader
from kalshi_trader.execution.live_trader import LiveTrader
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


def test_live_trader_execute_success():
    cfg = KalshiConfig()
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"order_id": "live-123", "status": "resting"}
    trader = LiveTrader(mock_client, cfg)
    result = trader.execute(make_signal(), current_price=45)
    assert result["status"] == "resting"
    mock_client.place_order.assert_called_once()


def test_live_trader_execute_rejected_on_error():
    cfg = KalshiConfig()
    mock_client = MagicMock()
    mock_client.place_order.side_effect = RuntimeError("API error")
    trader = LiveTrader(mock_client, cfg)
    result = trader.execute(make_signal(), current_price=45)
    assert result["status"] == "rejected"
    assert "API error" in result["reason"]


def test_paper_trader_does_not_overwrite_open_position(tmp_path):
    """Executing a second signal for the same ticker should be rejected."""
    cfg = KalshiConfig(data_dir=str(tmp_path))
    trader = PaperTrader(cfg, initial_bankroll=1000.0)
    sig = make_signal("DUPE-1")
    trader.execute(sig, current_price=45)
    result = trader.execute(sig, current_price=50)  # second call, same ticker
    assert result.get("status") == "rejected"
    # Position should still reflect the original entry
    positions = trader.get_positions()
    assert len(positions) == 1
    assert positions[0]["entry_price"] == 45


def test_live_trader_close_position_not_found():
    cfg = KalshiConfig()
    mock_client = MagicMock()
    mock_client.get_positions.return_value = []
    trader = LiveTrader(mock_client, cfg)
    result = trader.close_position("NONEXISTENT")
    assert result is False


def test_live_trader_close_uses_sell_action():
    """close_position must place a SELL order, not a BUY."""
    cfg = KalshiConfig()
    mock_client = MagicMock()
    mock_client.get_positions.return_value = [
        {"ticker": "CLOSE-1", "side": "yes", "quantity": 2}
    ]
    mock_client.place_order.return_value = {"order_id": "x", "status": "filled"}
    trader = LiveTrader(mock_client, cfg)
    result = trader.close_position("CLOSE-1")
    assert result is True
    call_kwargs = mock_client.place_order.call_args
    # Verify action="sell" was passed
    assert call_kwargs.kwargs.get("action") == "sell"
