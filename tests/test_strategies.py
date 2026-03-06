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


def test_directional_no_signal_below_threshold():
    s = DirectionalStrategy(confidence_threshold=0.7)
    sig = s.on_market_update(make_snapshot(), make_signals())
    # No external signals → confidence below threshold
    assert sig is None


def test_arbitrage_no_signal_when_no_pairs():
    s = ArbitrageStrategy()
    sig = s.on_market_update(make_snapshot(), make_signals())
    assert sig is None
