import time
from kalshi_trader.strategies.base_strategy import BaseStrategy
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals, Signal


class AlwaysBuyYes(BaseStrategy):
    name = "AlwaysBuyYes"

    def on_market_update(self, market, signals):
        return Signal(
            ticker=market.ticker, direction="yes",
            confidence=0.9, size=1,
            strategy_name=self.name, reason="test",
            timestamp=int(time.time()),
        )


def make_snapshot():
    return MarketSnapshot(
        ticker="TEST-1", timestamp=int(time.time()),
        yes_bid=40, yes_ask=42, no_bid=58, no_ask=60,
        volume=100, open_interest=50, category="financial"
    )


def make_signals():
    return ExternalSignals(timestamp=int(time.time()))


def test_strategy_returns_signal():
    s = AlwaysBuyYes()
    sig = s.on_market_update(make_snapshot(), make_signals())
    assert sig is not None
    assert sig.direction == "yes"
    assert 0.0 <= sig.confidence <= 1.0


def test_strategy_can_return_none():
    class NeverTrades(BaseStrategy):
        name = "NeverTrades"
        def on_market_update(self, market, signals):
            return None

    s = NeverTrades()
    assert s.on_market_update(make_snapshot(), make_signals()) is None


def test_signal_direction_valid():
    sig = Signal(ticker="T", direction="yes", confidence=0.8,
                 size=1, strategy_name="test", reason="r")
    assert sig.direction in ("yes", "no")


from kalshi_trader.strategies.market_maker import MarketMakerStrategy
from kalshi_trader.strategies.directional import DirectionalStrategy
from kalshi_trader.strategies.arbitrage import ArbitrageStrategy


def test_market_maker_signals_on_wide_spread():
    s = MarketMakerStrategy(min_spread=3)
    snap = make_snapshot()  # spread=2 (42-40), below min_spread=3
    assert s.on_market_update(snap, make_signals()) is None

    snap2 = MarketSnapshot(
        ticker="TEST-2", timestamp=int(time.time()),
        yes_bid=38, yes_ask=44, no_bid=56, no_ask=62,
        volume=500, open_interest=200, category="financial"
    )  # spread=6, above min
    sig = s.on_market_update(snap2, make_signals())
    assert sig is not None
    assert sig.direction in ("yes", "no")


def test_market_maker_uses_effective_no_bid():
    """MarketMaker must use effective_no_bid when no_bid is None."""
    s = MarketMakerStrategy(min_spread=3, min_volume=0)
    snap = MarketSnapshot(
        ticker="T", timestamp=1700000000,
        yes_bid=30, yes_ask=35, no_bid=None, no_ask=None,
        volume=50, open_interest=50, category="financial",
    )
    # effective_no_bid = 100-35 = 65, yes_bid=30 < 65 → direction="yes"
    sig = s.on_market_update(snap, make_signals())
    assert sig is not None
    assert sig.direction == "yes"


def test_market_maker_no_volume_filter_default():
    """MarketMaker with min_volume=0 should signal on zero-volume markets."""
    s = MarketMakerStrategy(min_spread=3, min_volume=0)
    snap = MarketSnapshot(
        ticker="T", timestamp=1700000000,
        yes_bid=30, yes_ask=38, no_bid=62, no_ask=70,
        volume=0, open_interest=0, category="financial",
    )
    sig = s.on_market_update(snap, make_signals())
    assert sig is not None


def test_directional_no_signal_below_threshold():
    s = DirectionalStrategy(confidence_threshold=0.7)
    sig = s.on_market_update(make_snapshot(), make_signals())
    # No external signals → confidence below threshold
    assert sig is None


def test_arbitrage_no_signal_when_no_pairs():
    s = ArbitrageStrategy()
    sig = s.on_market_update(make_snapshot(), make_signals())
    assert sig is None


def test_on_exit_profit_target_yes():
    """on_exit returns True when YES profit target is hit."""
    s = MarketMakerStrategy(exit_profit_cents=10)
    # Entry at 40, current mid=51 → profit=11 >= 10
    snap = MarketSnapshot(
        ticker="T", timestamp=int(time.time()),
        yes_bid=50, yes_ask=52, no_bid=48, no_ask=50,
        volume=100, open_interest=50, category="financial"
    )
    assert s.on_exit(entry_price=40, entry_ts=int(time.time()), direction="yes",
                     market=snap, signals=make_signals()) is True


def test_on_exit_profit_target_not_hit():
    """on_exit returns False when profit target not yet reached."""
    s = MarketMakerStrategy(exit_profit_cents=20)
    snap = make_snapshot()  # mid=41, entry=40, profit=1 < 20
    assert s.on_exit(entry_price=40, entry_ts=int(time.time()), direction="yes",
                     market=snap, signals=make_signals()) is False


def test_on_exit_time_limit():
    """on_exit returns True when time limit exceeded."""
    s = DirectionalStrategy(exit_time_hours=1)
    old_ts = int(time.time()) - 3700  # over 1 hour ago
    assert s.on_exit(entry_price=45, entry_ts=old_ts, direction="yes",
                     market=make_snapshot(), signals=make_signals()) is True


def test_on_exit_no_exit_when_disabled():
    """on_exit returns False when both checks are disabled (0)."""
    s = ArbitrageStrategy(exit_profit_cents=0, exit_time_hours=0)
    assert s.on_exit(entry_price=45, entry_ts=int(time.time()), direction="yes",
                     market=make_snapshot(), signals=make_signals()) is False


def test_on_exit_no_direction():
    """on_exit for NO direction: profit when YES price falls.

    entry_price=58 means we paid 58c for the NO contract (YES was at 42c).
    Current YES mid = (28+32)/2 = 30c → current NO mid = 100 - 30 = 70c.
    Profit = current_NO_mid - entry_NO_price = (100 - 30) - 58 = 12c >= 10c target.
    """
    s = MarketMakerStrategy(exit_profit_cents=10)
    snap = MarketSnapshot(
        ticker="T", timestamp=int(time.time()),
        yes_bid=28, yes_ask=32, no_bid=68, no_ask=72,
        volume=100, open_interest=50, category="financial"
    )
    assert s.on_exit(entry_price=58, entry_ts=int(time.time()), direction="no",
                     market=snap, signals=make_signals()) is True


def test_on_exit_none_entry_price_skips_profit_check():
    """on_exit with entry_price=None must not raise and must return False for profit check."""
    s = MarketMakerStrategy(exit_profit_cents=10)
    snap = make_snapshot()
    result = s.on_exit(entry_price=None, entry_ts=int(time.time()), direction="yes",
                       market=snap, signals=make_signals())
    assert result is False


def test_on_exit_none_entry_ts_skips_time_check():
    """on_exit with entry_ts=None must not raise and must return False for time check."""
    s = DirectionalStrategy(exit_time_hours=1)
    result = s.on_exit(entry_price=45, entry_ts=None, direction="yes",
                       market=make_snapshot(), signals=make_signals())
    assert result is False


def test_snapshot_computes_no_prices_from_yes():
    """no_bid/no_ask should be computed from yes prices when stored as None."""
    snap = MarketSnapshot(
        ticker="T", timestamp=1700000000,
        yes_bid=40, yes_ask=45, no_bid=None, no_ask=None,
        volume=100, open_interest=50, category="financial",
    )
    assert snap.effective_no_bid == 55
    assert snap.effective_no_ask == 60


def test_on_exit_time_limit_uses_current_ts():
    """on_exit should accept optional current_ts for backtesting instead of wall clock."""
    s = DirectionalStrategy(exit_time_hours=1)
    snap = make_snapshot()
    result = s.on_exit(entry_price=45, entry_ts=1000, direction="yes",
                       market=snap, signals=make_signals(), current_ts=4700)
    assert result is True


def test_on_exit_time_limit_not_hit_with_current_ts():
    """on_exit with current_ts should not exit if time limit not reached."""
    s = DirectionalStrategy(exit_time_hours=1)
    snap = make_snapshot()
    result = s.on_exit(entry_price=45, entry_ts=1000, direction="yes",
                       market=snap, signals=make_signals(), current_ts=2000)
    assert result is False
