import time
from kalshi_trader.risk.risk_manager import RiskManager
from kalshi_trader.data.models import Signal
from kalshi_trader.config import KalshiConfig


def make_signal(ticker="TEST-1", confidence=0.8, size=1):
    return Signal(
        ticker=ticker, direction="yes", confidence=confidence,
        size=size, strategy_name="test", reason="test",
        timestamp=int(time.time()),
    )


def test_signal_approved_within_limits():
    cfg = KalshiConfig(max_position_pct=0.05, max_total_exposure_pct=0.30)
    rm = RiskManager(cfg, bankroll=1000.0)
    sig = make_signal()
    approved, reason = rm.validate(sig, current_price=45)
    assert approved


def test_signal_rejected_daily_loss_limit():
    cfg = KalshiConfig(daily_loss_limit_pct=0.03)
    rm = RiskManager(cfg, bankroll=1000.0)
    rm.record_daily_loss(31.0)  # 3.1% of $1000
    sig = make_signal()
    approved, reason = rm.validate(sig, current_price=45)
    assert not approved
    assert "daily loss" in reason.lower()


def test_signal_rejected_over_max_exposure():
    cfg = KalshiConfig(max_total_exposure_pct=0.10)
    rm = RiskManager(cfg, bankroll=1000.0)
    rm.record_open_position("OTHER-1", exposure=105.0)  # 10.5% > 10%
    sig = make_signal()
    approved, reason = rm.validate(sig, current_price=45)
    assert not approved
    assert "exposure" in reason.lower()


def test_size_capped_by_max_position_pct():
    cfg = KalshiConfig(max_position_pct=0.05)
    rm = RiskManager(cfg, bankroll=1000.0)
    # Max position = $50; at 45c per contract → max ~111 contracts
    size = rm.size_position(current_price=45)
    assert size <= 111
    assert size > 0


def test_signal_rejected_over_category_exposure():
    cfg = KalshiConfig(max_category_exposure_pct=0.10)
    rm = RiskManager(cfg, bankroll=1000.0)
    # Record $105 exposure in "financial" category (10.5% of $1000)
    rm.record_open_position("OTHER-1", exposure=105.0, category="financial")
    sig = make_signal()
    approved, reason = rm.validate(sig, current_price=45, category="financial")
    assert not approved
    assert "category" in reason.lower()


def test_different_category_not_blocked():
    cfg = KalshiConfig(max_category_exposure_pct=0.10)
    rm = RiskManager(cfg, bankroll=1000.0)
    rm.record_open_position("OTHER-1", exposure=105.0, category="financial")
    sig = make_signal()
    # Different category should not be blocked
    approved, _ = rm.validate(sig, current_price=45, category="politics")
    assert approved


def test_position_meta_stored_and_retrievable():
    cfg = KalshiConfig()
    rm = RiskManager(cfg, bankroll=1000.0)
    rm.record_open_position(
        "TEST-1", exposure=45.0, category="financial",
        entry_price=45, entry_ts=int(time.time()),
        direction="yes", strategy_name="MarketMaker",
    )
    assert rm.has_position("TEST-1")
    meta = rm.get_position_meta("TEST-1")
    assert meta is not None
    assert meta.entry_price == 45
    assert meta.strategy_name == "MarketMaker"
    assert meta.direction == "yes"


def test_has_position_false_when_absent():
    cfg = KalshiConfig()
    rm = RiskManager(cfg, bankroll=1000.0)
    assert not rm.has_position("NONEXISTENT")


def test_close_position_removes_meta():
    cfg = KalshiConfig()
    rm = RiskManager(cfg, bankroll=1000.0)
    rm.record_open_position("TEST-1", exposure=10.0)
    rm.close_position("TEST-1")
    assert not rm.has_position("TEST-1")
    assert rm.get_position_meta("TEST-1") is None
