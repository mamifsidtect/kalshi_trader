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
