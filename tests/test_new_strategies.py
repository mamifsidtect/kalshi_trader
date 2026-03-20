"""Tests for new formulaic strategies: SingleConditionArb, BregmanDivergence, KellySizer."""
import time
import math
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals
from kalshi_trader.strategies.single_condition_arb import SingleConditionArbStrategy
from kalshi_trader.strategies.bregman_divergence import (
    BregmanDivergenceStrategy, kl_divergence, estimate_fair_value,
)
from kalshi_trader.strategies.kelly_sizer import kelly_size
from kalshi_trader.research.backtester import Backtester, BacktestResult
from kalshi_trader.research.parameter_sweeper import ParameterSweeper, SweepReport
from kalshi_trader.config import KalshiConfig


def _snap(yes_bid=40, yes_ask=42, no_bid=58, no_ask=60, volume=100, ticker="T"):
    return MarketSnapshot(
        ticker=ticker, timestamp=1700000000,
        yes_bid=yes_bid, yes_ask=yes_ask, no_bid=no_bid, no_ask=no_ask,
        volume=volume, open_interest=50, category="financial",
    )


def _signals(**kwargs):
    return ExternalSignals(timestamp=1700000000, **kwargs)


# --- SingleConditionArbStrategy ---


def test_single_arb_fires_when_sum_below_100():
    """When yes_ask + no_ask < 100, there's guaranteed arbitrage."""
    s = SingleConditionArbStrategy(min_edge_cents=3)
    snap = _snap(yes_ask=42, no_ask=50)  # total=92, edge=8
    sig = s.on_market_update(snap, _signals())
    assert sig is not None
    assert sig.strategy_name == "SingleConditionArb"
    assert "edge=8" in sig.reason


def test_single_arb_skips_when_sum_near_100():
    """No signal when sum is close to 100 (below min_edge)."""
    s = SingleConditionArbStrategy(min_edge_cents=5)
    snap = _snap(yes_ask=48, no_ask=50)  # total=98, edge=2 < 5
    assert s.on_market_update(snap, _signals()) is None


def test_single_arb_skips_when_sum_above_100():
    """No signal when sum >= 100 (no buy-both arbitrage)."""
    s = SingleConditionArbStrategy(min_edge_cents=1)
    snap = _snap(yes_ask=55, no_ask=50)  # total=105
    assert s.on_market_update(snap, _signals()) is None


def test_single_arb_picks_cheaper_side():
    """Direction should be the cheaper ask price."""
    s = SingleConditionArbStrategy(min_edge_cents=1)
    snap = _snap(yes_ask=30, no_ask=60)  # yes is cheaper
    sig = s.on_market_update(snap, _signals())
    assert sig.direction == "yes"

    snap2 = _snap(yes_ask=60, no_ask=30)  # no is cheaper
    sig2 = s.on_market_update(snap2, _signals())
    assert sig2.direction == "no"


def test_single_arb_respects_max_entry_price():
    """Skip when cheaper side exceeds max_entry_price."""
    s = SingleConditionArbStrategy(min_edge_cents=1, max_entry_price=40)
    snap = _snap(yes_ask=45, no_ask=45)  # total=90, edge=10, but cheapest=45 > 40
    assert s.on_market_update(snap, _signals()) is None


def test_single_arb_handles_none_prices():
    snap = MarketSnapshot(
        ticker="T", timestamp=1700000000,
        yes_bid=40, yes_ask=None, no_bid=58, no_ask=60,
        volume=100, open_interest=50, category="financial",
    )
    s = SingleConditionArbStrategy()
    assert s.on_market_update(snap, _signals()) is None


# --- BregmanDivergenceStrategy ---


def test_kl_divergence_same_distribution():
    """KL(p||p) = 0 for any p."""
    assert abs(kl_divergence(0.5, 0.5)) < 1e-10
    assert abs(kl_divergence(0.8, 0.8)) < 1e-10


def test_kl_divergence_asymmetric():
    """KL divergence is asymmetric: D(p||q) != D(q||p) in general."""
    # Use non-complementary values (p+q != 1) to show asymmetry
    d1 = kl_divergence(0.2, 0.6)
    d2 = kl_divergence(0.6, 0.2)
    assert d1 > 0
    assert d2 > 0
    assert abs(d1 - d2) > 0.001  # not equal


def test_kl_divergence_increases_with_distance():
    """KL divergence should grow as distributions diverge."""
    d_close = kl_divergence(0.5, 0.55)
    d_far = kl_divergence(0.5, 0.9)
    assert d_far > d_close


def test_bregman_fires_with_external_signal():
    """BregmanDivergence should fire when external price diverges from market."""
    s = BregmanDivergenceStrategy(min_divergence=0.01)
    snap = _snap(yes_bid=30, yes_ask=40)  # mid=35, market_prob=0.35
    signals = _signals(correlated_prices={"T": 0.70})  # external says 0.70
    sig = s.on_market_update(snap, signals)
    assert sig is not None
    assert sig.direction == "yes"  # fair > market → buy yes
    assert "KL=" in sig.reason


def test_bregman_skips_small_divergence():
    """No signal when KL divergence is below threshold."""
    s = BregmanDivergenceStrategy(min_divergence=0.5)
    snap = _snap(yes_bid=48, yes_ask=52)  # mid=50, prob=0.50
    signals = _signals(correlated_prices={"T": 0.52})  # very close
    assert s.on_market_update(snap, signals) is None


def test_bregman_no_signal_without_data():
    """No signal when there's only a market prior (weight too low)."""
    s = BregmanDivergenceStrategy(min_divergence=0.01)
    snap = _snap(yes_bid=30, yes_ask=40)
    # Only market mid_price available → fair_value ≈ market_prob → low divergence
    assert s.on_market_update(snap, _signals()) is None


def test_estimate_fair_value_with_polls():
    snap = _snap()
    signals = _signals(poll_data=[{"value": 0.75}])
    fv, sources = estimate_fair_value(snap, signals)
    assert fv is not None
    assert 0.0 < fv < 1.0
    assert "polls" in sources


def test_estimate_fair_value_none_without_signals():
    """With no mid_price and no signals, should return None."""
    snap = MarketSnapshot(
        ticker="T", timestamp=1700000000,
        yes_bid=None, yes_ask=None, no_bid=None, no_ask=None,
        volume=0, open_interest=0, category="financial",
    )
    fv, _ = estimate_fair_value(snap, _signals())
    assert fv is None


# --- Kelly Position Sizer ---


def test_kelly_returns_zero_no_edge():
    """No edge → 0 contracts."""
    snap = _snap(volume=200)
    assert kelly_size(0, 50, snap) == 0
    assert kelly_size(-5, 50, snap) == 0


def test_kelly_returns_positive_with_edge():
    snap = _snap(volume=200)
    size = kelly_size(edge_cents=10, entry_price=50, market=snap)
    assert size >= 1


def test_kelly_respects_max_contracts():
    snap = _snap(volume=10000)
    size = kelly_size(edge_cents=30, entry_price=20, market=snap, max_contracts=3)
    assert size <= 3


def test_kelly_reduces_for_low_volume():
    snap_low = _snap(volume=5)
    snap_high = _snap(volume=500)
    size_low = kelly_size(edge_cents=10, entry_price=50, market=snap_low, max_contracts=50)
    size_high = kelly_size(edge_cents=10, entry_price=50, market=snap_high, max_contracts=50)
    assert size_low <= size_high


def test_kelly_caps_at_order_book_depth():
    """Should not exceed volume/4 to avoid moving the market."""
    snap = _snap(volume=8)  # depth_cap = 8//4 = 2
    size = kelly_size(edge_cents=20, entry_price=30, market=snap, max_contracts=100)
    assert size <= 2


# --- VWAP Slippage ---


def test_vwap_slippage_backtester():
    """Backtester with vwap_slippage=True should still produce valid results."""
    cfg = KalshiConfig()
    bt = Backtester(cfg, vwap_slippage=True)
    from kalshi_trader.strategies.market_maker import MarketMakerStrategy

    snaps = []
    for i in range(10):
        snaps.append(MarketSnapshot(
            ticker="T", timestamp=1700000000 + i * 60,
            yes_bid=45, yes_ask=50, no_bid=50, no_ask=55,
            volume=500, open_interest=200, category="financial",
            settled=True,
        ))

    strategy = MarketMakerStrategy(min_spread=3)
    signals_obj = ExternalSignals(timestamp=1700000000)
    result = bt.run(strategy, snaps, lambda ts: signals_obj)
    assert isinstance(result, BacktestResult)


def test_vwap_slippage_higher_for_low_volume():
    """VWAP slippage should be higher for low-volume markets."""
    cfg = KalshiConfig()
    bt = Backtester(cfg, vwap_slippage=True)
    snap_low = _snap(volume=1)
    snap_high = _snap(volume=1000)
    slip_low = bt._estimate_vwap_slippage(snap_low, 1)
    slip_high = bt._estimate_vwap_slippage(snap_high, 1)
    assert slip_low >= slip_high


# --- Parameter Sweeper ---


def test_sweeper_returns_report():
    cfg = KalshiConfig()
    sweeper = ParameterSweeper(cfg)

    snaps = []
    for i in range(20):
        snaps.append(MarketSnapshot(
            ticker="T", timestamp=1700000000 + i * 60,
            yes_bid=30, yes_ask=40, no_bid=60, no_ask=70,
            volume=500, open_interest=200, category="financial",
            settled=True if i == 19 else None,
        ))

    signals_obj = ExternalSignals(timestamp=1700000000)
    report = sweeper.sweep(
        "SingleConditionArb", snaps, lambda ts: signals_obj,
        param_grid={"min_edge_cents": [1, 5], "max_entry_price": [90, 95], "contracts": [1]},
    )
    assert isinstance(report, SweepReport)
    assert report.total_combinations == 4
    assert len(report.all_results) == 4


def test_sweeper_unknown_strategy_raises():
    cfg = KalshiConfig()
    sweeper = ParameterSweeper(cfg)
    try:
        sweeper.sweep("NonexistentStrategy", [], lambda ts: _signals())
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


# --- Integration: new strategies through backtester ---


def test_single_arb_backtest_integration():
    """SingleConditionArb should produce trades when prices are mispriced."""
    cfg = KalshiConfig()
    bt = Backtester(cfg)
    strategy = SingleConditionArbStrategy(min_edge_cents=5)

    snaps = [
        MarketSnapshot(
            ticker="T", timestamp=1700000000,
            yes_bid=30, yes_ask=40, no_bid=50, no_ask=52,  # total_cost=92, edge=8
            volume=500, open_interest=200, category="financial",
        ),
        MarketSnapshot(
            ticker="T", timestamp=1700000060,
            yes_bid=98, yes_ask=99, no_bid=1, no_ask=2,
            volume=500, open_interest=200, category="financial",
            settled=True,
        ),
    ]
    signals_obj = ExternalSignals(timestamp=1700000000)
    result = bt.run(strategy, snaps, lambda ts: signals_obj)
    assert result.total_trades == 1
    assert result.trade_log[0]["direction"] == "yes"  # yes_ask=40 < no_ask=52


def test_bregman_backtest_integration():
    """BregmanDivergence should trade when external signals diverge from market."""
    cfg = KalshiConfig()
    bt = Backtester(cfg)
    strategy = BregmanDivergenceStrategy(min_divergence=0.01)

    snaps = [
        MarketSnapshot(
            ticker="T", timestamp=1700000000,
            yes_bid=30, yes_ask=35, no_bid=65, no_ask=70,  # mid=32.5, prob=0.325
            volume=500, open_interest=200, category="financial",
        ),
        MarketSnapshot(
            ticker="T", timestamp=1700000060,
            yes_bid=98, yes_ask=99, no_bid=1, no_ask=2,
            volume=500, open_interest=200, category="financial",
            settled=True,
        ),
    ]
    # External signal says probability is 0.80 → big divergence from 0.325
    signals_obj = ExternalSignals(
        timestamp=1700000000,
        correlated_prices={"T": 0.80},
    )
    result = bt.run(strategy, snaps, lambda ts: signals_obj)
    assert result.total_trades == 1
    assert result.trade_log[0]["direction"] == "yes"  # fair > market
