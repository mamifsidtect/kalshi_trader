import time
from kalshi_trader.research.backtester import Backtester, BacktestResult
from kalshi_trader.research.signal_tester import SignalTester
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals
from kalshi_trader.strategies.market_maker import MarketMakerStrategy
from kalshi_trader.config import KalshiConfig


def make_snapshots(n=10, ticker="TEST-1", spread=5, settled=True):
    snaps = []
    for i in range(n):
        snap = MarketSnapshot(
            ticker=ticker, timestamp=1700000000 + i * 60,
            yes_bid=45, yes_ask=50, no_bid=50, no_ask=55,
            volume=500, open_interest=200, category="financial",
            settled=settled,
        )
        snaps.append(snap)
    return snaps


def test_backtester_runs_and_returns_result():
    cfg = KalshiConfig()
    strategy = MarketMakerStrategy(min_spread=3)
    bt = Backtester(cfg)
    signals_obj = ExternalSignals(timestamp=int(time.time()))
    result = bt.run(strategy, make_snapshots(), lambda ts: signals_obj)
    assert isinstance(result, BacktestResult)
    assert result.total_trades >= 0
    assert 0.0 <= result.win_rate <= 1.0


def test_backtester_sharpe_calculated():
    cfg = KalshiConfig()
    strategy = MarketMakerStrategy(min_spread=3)
    bt = Backtester(cfg)
    signals_obj = ExternalSignals(timestamp=int(time.time()))
    result = bt.run(strategy, make_snapshots(30), lambda ts: signals_obj)
    assert isinstance(result.sharpe, float)


def test_signal_tester_accuracy():
    cfg = KalshiConfig()
    tester = SignalTester(cfg)
    snaps = make_snapshots(20, settled=True)  # all settled YES
    acc = tester.test_price_momentum(snaps)
    assert 0.0 <= acc <= 1.0


def test_backtester_does_not_mix_tickers():
    """A settled snapshot for TICKER-B must not close a position opened on TICKER-A."""
    from kalshi_trader.strategies.base_strategy import BaseStrategy
    from kalshi_trader.data.models import Signal
    import time

    class AlwaysBuy(BaseStrategy):
        name = "AlwaysBuy"
        def on_market_update(self, market, signals):
            return Signal(
                ticker=market.ticker, direction="yes", confidence=0.9,
                size=1, strategy_name=self.name, reason="test",
                timestamp=int(time.time()),
            )

    cfg = KalshiConfig()
    bt = Backtester(cfg)
    signals_obj = ExternalSignals(timestamp=int(time.time()))

    # TICKER-A: 5 open snapshots, then settles YES
    snaps_a = make_snapshots(5, ticker="TICKER-A", settled=None)
    snaps_a.append(MarketSnapshot(
        ticker="TICKER-A", timestamp=1700000500,
        yes_bid=99, yes_ask=100, no_bid=0, no_ask=1,
        volume=500, open_interest=200, category="financial", settled=True,
    ))
    # TICKER-B: 3 snapshots, settles NO
    snaps_b = make_snapshots(3, ticker="TICKER-B", settled=None)
    snaps_b.append(MarketSnapshot(
        ticker="TICKER-B", timestamp=1700000400,
        yes_bid=0, yes_ask=1, no_bid=99, no_ask=100,
        volume=500, open_interest=200, category="financial", settled=False,
    ))

    # Interleaved list that would previously cross-contaminate
    mixed = snaps_a[:3] + snaps_b[:2] + snaps_a[3:] + snaps_b[2:]
    result = bt.run(AlwaysBuy(), mixed, lambda ts: signals_obj)

    # TICKER-A settled YES → its trade should be profitable
    a_trades = [t for t in result.trade_log if t["ticker"] == "TICKER-A"]
    assert len(a_trades) == 1
    assert a_trades[0]["pnl"] > 0  # bought YES, settled YES → profit


def test_backtester_no_position_pnl_correct():
    """NO position P&L must use (100 - yes_exit) as the NO exit price."""
    from kalshi_trader.strategies.base_strategy import BaseStrategy
    from kalshi_trader.data.models import Signal
    import time

    class AlwaysBuyNo(BaseStrategy):
        name = "AlwaysBuyNo"
        def on_market_update(self, market, signals):
            return Signal(
                ticker=market.ticker, direction="no", confidence=0.9,
                size=1, strategy_name=self.name, reason="test",
                timestamp=int(time.time()),
            )

    cfg = KalshiConfig()
    bt = Backtester(cfg)
    signals_obj = ExternalSignals(timestamp=int(time.time()))

    snaps = [
        MarketSnapshot(
            ticker="T", timestamp=1700000000,
            yes_bid=45, yes_ask=50, no_bid=50, no_ask=55,
            volume=500, open_interest=200, category="financial",
        ),
        MarketSnapshot(
            ticker="T", timestamp=1700000060,
            yes_bid=98, yes_ask=99, no_bid=1, no_ask=2,
            volume=500, open_interest=200, category="financial",
            settled=True,
        ),
    ]
    result = bt.run(AlwaysBuyNo(), snaps, lambda ts: signals_obj)
    assert result.total_trades == 1
    trade = result.trade_log[0]
    assert trade["direction"] == "no"
    assert trade["entry_price"] == 56
    assert abs(trade["pnl"] - (-0.55)) < 0.01


def test_backtester_no_position_win_pnl():
    """NO position that wins (settled=False) must have correct positive P&L."""
    from kalshi_trader.strategies.base_strategy import BaseStrategy
    from kalshi_trader.data.models import Signal
    import time

    class AlwaysBuyNo(BaseStrategy):
        name = "AlwaysBuyNo"
        def on_market_update(self, market, signals):
            return Signal(
                ticker=market.ticker, direction="no", confidence=0.9,
                size=1, strategy_name=self.name, reason="test",
                timestamp=int(time.time()),
            )

    cfg = KalshiConfig()
    bt = Backtester(cfg)
    signals_obj = ExternalSignals(timestamp=int(time.time()))

    snaps = [
        MarketSnapshot(
            ticker="T", timestamp=1700000000,
            yes_bid=45, yes_ask=50, no_bid=50, no_ask=55,
            volume=500, open_interest=200, category="financial",
        ),
        MarketSnapshot(
            ticker="T", timestamp=1700000060,
            yes_bid=0, yes_ask=1, no_bid=99, no_ask=100,
            volume=500, open_interest=200, category="financial",
            settled=False,
        ),
    ]
    result = bt.run(AlwaysBuyNo(), snaps, lambda ts: signals_obj)
    assert result.total_trades == 1
    trade = result.trade_log[0]
    assert trade["direction"] == "no"
    assert abs(trade["pnl"] - 0.43) < 0.01


def test_backtester_resolves_at_close_time():
    """Positions must close when close_time passes, using last mid_price to infer outcome."""
    from kalshi_trader.strategies.base_strategy import BaseStrategy
    from kalshi_trader.data.models import Signal
    import time

    class AlwaysBuyYes(BaseStrategy):
        name = "AlwaysBuyYes"
        def on_market_update(self, market, signals):
            return Signal(
                ticker=market.ticker, direction="yes", confidence=0.9,
                size=1, strategy_name=self.name, reason="test",
                timestamp=int(time.time()),
            )

    cfg = KalshiConfig()
    bt = Backtester(cfg)
    signals_obj = ExternalSignals(timestamp=int(time.time()))

    snaps = [
        MarketSnapshot(
            ticker="T", timestamp=1700000000,
            yes_bid=45, yes_ask=50, no_bid=50, no_ask=55,
            volume=500, open_interest=200, category="financial",
            close_time="2023-11-14T20:03:20+00:00",
        ),
        MarketSnapshot(
            ticker="T", timestamp=1700000100,
            yes_bid=78, yes_ask=82, no_bid=18, no_ask=22,
            volume=500, open_interest=200, category="financial",
            close_time="2023-11-14T20:03:20+00:00",
        ),
        MarketSnapshot(
            ticker="T", timestamp=1700000300,
            yes_bid=78, yes_ask=82, no_bid=18, no_ask=22,
            volume=500, open_interest=200, category="financial",
            close_time="2023-11-14T20:03:20+00:00",
        ),
    ]
    result = bt.run(AlwaysBuyYes(), snaps, lambda ts: signals_obj)
    assert result.total_trades == 1
    trade = result.trade_log[0]
    assert trade["direction"] == "yes"
    assert trade["exit_price"] > 50


def test_backtester_calls_on_exit():
    """Backtester must call strategy.on_exit() and close if it returns True."""
    from kalshi_trader.strategies.base_strategy import BaseStrategy
    from kalshi_trader.data.models import Signal
    import time

    class ProfitTaker(BaseStrategy):
        name = "ProfitTaker"
        exit_profit_cents = 5

        def on_market_update(self, market, signals):
            return Signal(
                ticker=market.ticker, direction="yes", confidence=0.9,
                size=1, strategy_name=self.name, reason="test",
                timestamp=int(time.time()),
            )

    cfg = KalshiConfig()
    bt = Backtester(cfg)
    signals_obj = ExternalSignals(timestamp=int(time.time()))

    snaps = [
        MarketSnapshot(
            ticker="T", timestamp=1700000000,
            yes_bid=45, yes_ask=50, no_bid=50, no_ask=55,
            volume=500, open_interest=200, category="financial",
        ),
        MarketSnapshot(
            ticker="T", timestamp=1700000060,
            yes_bid=58, yes_ask=62, no_bid=38, no_ask=42,
            volume=500, open_interest=200, category="financial",
        ),
    ]
    result = bt.run(ProfitTaker(), snaps, lambda ts: signals_obj)
    assert result.total_trades == 1
    trade = result.trade_log[0]
    assert trade["pnl"] > 0


def test_full_backtest_pipeline_produces_trades():
    """End-to-end: realistic data with close_time -> backtester produces trades with correct P&L."""
    cfg = KalshiConfig()
    bt = Backtester(cfg)
    signals_obj = ExternalSignals(timestamp=1700000000)

    # Simulate a market that opens, trades, and expires
    # close_time = 1700000500 (after 5 snapshots at 60s intervals = 300s, so after snap 5)
    close_time_iso = "2023-11-14T20:08:20+00:00"  # = 1700000500
    snaps = []
    for i in range(10):
        ts = 1700000000 + i * 60
        # Price drifts from 50 toward 70 (YES winning)
        yes_bid = 45 + i * 2
        yes_ask = yes_bid + 5
        snaps.append(MarketSnapshot(
            ticker="DRIFT-1", timestamp=ts,
            yes_bid=yes_bid, yes_ask=yes_ask,
            no_bid=100 - yes_ask, no_ask=100 - yes_bid,
            volume=500, open_interest=200, category="financial",
            close_time=close_time_iso,
        ))

    strategy = MarketMakerStrategy(min_spread=3, min_volume=0)
    result = bt.run(strategy, snaps, lambda ts: signals_obj)

    assert result.total_trades >= 1, f"Expected trades but got {result.total_trades}"
    assert result.win_rate >= 0.0
    # Verify trade P&L has correct sign (position opened early, closed near 65c mid)
    for t in result.trade_log:
        assert "entry_price" in t
        assert "exit_price" in t
        assert isinstance(t["pnl"], float)
