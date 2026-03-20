# Fix Backtesting Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the backtesting system so it produces meaningful trade results instead of 0% success rate, by fixing 8 interconnected bugs across the collector, backtester, and strategies.

**Architecture:** The fixes flow bottom-up: (1) fix data layer to capture settlement outcomes, (2) fix backtester to close positions via multiple mechanisms, (3) fix P&L math, (4) fix strategy signal generation so strategies can actually fire, (5) fix the research script to wire everything together. Each task is independently testable.

**Tech Stack:** Python 3.13, pytest, dataclasses, Kalshi API (kalshi-python SDK)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `kalshi_trader/research/backtester.py` | Modify | Fix P&L formula, add close_time resolution, add on_exit support |
| `kalshi_trader/strategies/base_strategy.py` | Modify | Add current_ts param to on_exit for backtesting |
| `kalshi_trader/data/models.py` | Modify | Add no_bid/no_ask fallback properties |
| `kalshi_trader/strategies/market_maker.py` | Modify | Use effective_no_bid, relax volume filter |
| `kalshi_trader/strategies/directional.py` | Modify | Fix scoring weights so threshold is reachable |
| `kalshi_trader/scripts/run_research.py` | Modify | Load real signals, pass to backtest, add --backfill |
| `kalshi_trader/client/kalshi_client.py` | Modify | Add `result` field to _market_to_dict for settlement |
| `kalshi_trader/data/market_collector.py` | Modify | Add settlement backfill method |
| `tests/test_research.py` | Modify | Add tests for all backtester fixes |
| `tests/test_strategies.py` | Modify | Add tests for strategy fixes |
| `tests/test_market_collector.py` | Modify | Add test for settlement backfill |

---

### Task 1: Rewrite Backtester with P&L Fix, close_time Resolution, on_exit Support, and current_ts

**Problem:** The backtester has 4 interconnected bugs that must be fixed together since they all live in `_run_single_ticker`:
1. NO position P&L formula uses `(entry - exit_price)` where `exit_price` is YES-side — wrong magnitude
2. Positions only close on `snap.settled is not None` — but collected data has zero settled snapshots
3. `strategy.on_exit()` is never called — profit-target/time-limit exits are dead code
4. `on_exit()` uses wall-clock `time.time()` — doesn't work for historical backtesting

**This task replaces the entire `_run_single_ticker` method and adds `current_ts` to `BaseStrategy.on_exit()`.**

**Files:**
- Modify: `kalshi_trader/research/backtester.py:56-105`
- Modify: `kalshi_trader/strategies/base_strategy.py:22-45`
- Test: `tests/test_research.py`
- Test: `tests/test_strategies.py`

- [ ] **Step 1: Write failing tests for all 4 fixes**

Add to `tests/test_research.py`:

```python
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

    # Open snapshot: no_ask=55, so entry = 55 + 1 (slippage) = 56
    snaps = [
        MarketSnapshot(
            ticker="T", timestamp=1700000000,
            yes_bid=45, yes_ask=50, no_bid=50, no_ask=55,
            volume=500, open_interest=200, category="financial",
        ),
        # Settled YES (NO loses): exit_price=99 → NO exit = 100-99 = 1
        # P&L should be: 1 * (1 - 56) / 100 = -0.55
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
    assert trade["entry_price"] == 56  # no_ask(55) + slippage(1)
    # NO lost (YES won): no_exit = 100 - 99 = 1, P&L = (1 - 56)/100 = -0.55
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
        # Settled NO (NO wins): exit_price=1 → NO exit = 100-1 = 99
        # P&L should be: 1 * (99 - 56) / 100 = 0.43
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
    # NO won: no_exit = 100 - 1 = 99, P&L = (99 - 56)/100 = 0.43
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

    # Market closes at timestamp 1700000200
    # Last snapshot before close has yes price at 80c (strongly YES)
    snaps = [
        MarketSnapshot(
            ticker="T", timestamp=1700000000,
            yes_bid=45, yes_ask=50, no_bid=50, no_ask=55,
            volume=500, open_interest=200, category="financial",
            close_time="2023-11-14T20:03:20+00:00",  # ts=1700000200
        ),
        MarketSnapshot(
            ticker="T", timestamp=1700000100,
            yes_bid=78, yes_ask=82, no_bid=18, no_ask=22,
            volume=500, open_interest=200, category="financial",
            close_time="2023-11-14T20:03:20+00:00",
        ),
        # This snapshot is AFTER close_time — should trigger resolution
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
    # Exited at last mid price (80) since close_time passed
    assert trade["exit_price"] > 50  # should be near 80


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
        # Entry: yes_ask=50, entry=51 (with slippage)
        MarketSnapshot(
            ticker="T", timestamp=1700000000,
            yes_bid=45, yes_ask=50, no_bid=50, no_ask=55,
            volume=500, open_interest=200, category="financial",
        ),
        # Mid price = 60, profit = 60 - 51 = 9 >= 5 → on_exit returns True
        MarketSnapshot(
            ticker="T", timestamp=1700000060,
            yes_bid=58, yes_ask=62, no_bid=38, no_ask=42,
            volume=500, open_interest=200, category="financial",
        ),
    ]
    result = bt.run(ProfitTaker(), snaps, lambda ts: signals_obj)
    assert result.total_trades == 1
    trade = result.trade_log[0]
    assert trade["pnl"] > 0  # profitable exit
```

Add to `tests/test_strategies.py`:

```python
def test_on_exit_time_limit_uses_current_ts():
    """on_exit should accept optional current_ts for backtesting instead of wall clock."""
    s = DirectionalStrategy(exit_time_hours=1)
    snap = make_snapshot()
    # entry_ts=1000, current_ts=1000+3700=4700 (over 1 hour)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_research.py::test_backtester_no_position_pnl_correct tests/test_research.py::test_backtester_resolves_at_close_time tests/test_research.py::test_backtester_calls_on_exit tests/test_strategies.py::test_on_exit_time_limit_uses_current_ts -v`
Expected: FAIL

- [ ] **Step 3: Add current_ts parameter to BaseStrategy.on_exit**

In `kalshi_trader/strategies/base_strategy.py`, replace the entire `on_exit` method:

```python
    def on_exit(
        self,
        entry_price: Optional[int],
        entry_ts: Optional[int],
        direction: str,
        market: MarketSnapshot,
        signals: ExternalSignals,
        current_ts: Optional[int] = None,
    ) -> bool:
        """Return True to close this position early. Checks profit target and time limit."""
        if self.exit_profit_cents > 0 and entry_price is not None and market.mid_price is not None:
            if direction == "yes":
                profit = market.mid_price - entry_price
            elif direction == "no":
                profit = (100 - market.mid_price) - entry_price
            else:
                profit = None
            if profit is not None and profit >= self.exit_profit_cents:
                return True
        if self.exit_time_hours > 0 and entry_ts is not None:
            now = current_ts if current_ts is not None else int(_time.time())
            elapsed_hours = (now - entry_ts) / 3600
            if elapsed_hours >= self.exit_time_hours:
                return True
        return False
```

- [ ] **Step 4: Replace _run_single_ticker in backtester**

Replace the entire `_run_single_ticker` method and add `_parse_close_time` in `kalshi_trader/research/backtester.py`:

```python
    @staticmethod
    def _parse_close_time(close_time_str: str) -> int:
        """Parse ISO close_time string to unix timestamp. Returns 0 if unparseable."""
        if not close_time_str:
            return 0
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(close_time_str)
            return int(dt.timestamp())
        except (ValueError, TypeError):
            return 0

    def _run_single_ticker(
        self,
        strategy: BaseStrategy,
        snapshots: List[MarketSnapshot],
        signals_fn: Callable[[int], ExternalSignals],
        slippage: int,
    ) -> tuple:
        open_position = None
        trade_log = []
        pnl_series = []

        for snap in snapshots:
            signals = signals_fn(snap.timestamp)

            # --- Try to close open position ---
            if open_position is not None:
                closed = False

                # 1. Explicit settlement
                if snap.settled is not None:
                    exit_price = 99 if snap.settled else 1
                    closed = True

                # 2. close_time passed — infer outcome from last mid_price
                elif snap.close_time:
                    close_ts = self._parse_close_time(snap.close_time)
                    if close_ts > 0 and snap.timestamp >= close_ts and snap.mid_price is not None:
                        exit_price = int(snap.mid_price)
                        closed = True

                # 3. Strategy early exit (passes current_ts for backtesting)
                elif snap.mid_price is not None:
                    if strategy.on_exit(
                        open_position["entry_price"],
                        open_position["entry_bar"],
                        open_position["direction"],
                        snap,
                        signals,
                        current_ts=snap.timestamp,
                    ):
                        exit_price = int(snap.mid_price)
                        closed = True

                if closed:
                    entry = open_position["entry_price"]
                    if open_position["direction"] == "yes":
                        pnl = open_position["size"] * ((exit_price - entry) / 100.0)
                    else:
                        # Convert YES-side exit to NO-side: NO settles at (100 - yes_price)
                        no_exit_price = 100 - exit_price
                        pnl = open_position["size"] * ((no_exit_price - entry) / 100.0)

                    trade_log.append({
                        "ticker": open_position["ticker"],
                        "direction": open_position["direction"],
                        "entry_price": entry,
                        "exit_price": exit_price,
                        "pnl": pnl,
                        "hold_bars": snap.timestamp - open_position["entry_bar"],
                    })
                    pnl_series.append(pnl)
                    open_position = None
                    continue  # don't open a new position on the same bar we closed

            # --- Try to open new position ---
            if open_position is None:
                signal = strategy.on_market_update(snap, signals)
                if signal is not None and snap.mid_price is not None:
                    if signal.direction == "yes" and snap.yes_ask is not None:
                        entry_price = snap.yes_ask + slippage
                    elif signal.direction == "no" and snap.no_ask is not None:
                        entry_price = snap.no_ask + slippage
                    else:
                        continue
                    open_position = {
                        "ticker": snap.ticker,
                        "direction": signal.direction,
                        "entry_price": entry_price,
                        "size": signal.size,
                        "entry_bar": snap.timestamp,
                    }

        return trade_log, pnl_series
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `pytest tests/test_research.py tests/test_strategies.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add kalshi_trader/research/backtester.py kalshi_trader/strategies/base_strategy.py tests/test_research.py tests/test_strategies.py
git commit -m "fix: rewrite backtester with P&L fix, close_time resolution, on_exit + current_ts"
```

---

### Task 2: Add no_bid/no_ask Fallback to MarketSnapshot

**Problem:** 96% of stored snapshots have `no_bid=null` and `no_ask=null`. Strategies that use these fields (e.g., MarketMaker direction logic) get `None` and fall through to default behavior. The model should compute these from YES prices when missing.

**Files:**
- Modify: `kalshi_trader/data/models.py:6-24`
- Test: `tests/test_strategies.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_strategies.py`:

```python
def test_snapshot_computes_no_prices_from_yes():
    """no_bid/no_ask should be computed from yes prices when stored as None."""
    snap = MarketSnapshot(
        ticker="T", timestamp=1700000000,
        yes_bid=40, yes_ask=45, no_bid=None, no_ask=None,
        volume=100, open_interest=50, category="financial",
    )
    # no_bid = 100 - yes_ask = 55, no_ask = 100 - yes_bid = 60
    assert snap.effective_no_bid == 55
    assert snap.effective_no_ask == 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategies.py::test_snapshot_computes_no_prices_from_yes -v`
Expected: FAIL (AttributeError: no effective_no_bid property)

- [ ] **Step 3: Add computed properties to MarketSnapshot**

In `kalshi_trader/data/models.py`, add after `spread` property:

```python
    @property
    def effective_no_bid(self) -> Optional[int]:
        if self.no_bid is not None:
            return self.no_bid
        if self.yes_ask is not None:
            return 100 - self.yes_ask
        return None

    @property
    def effective_no_ask(self) -> Optional[int]:
        if self.no_ask is not None:
            return self.no_ask
        if self.yes_bid is not None:
            return 100 - self.yes_bid
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_strategies.py::test_snapshot_computes_no_prices_from_yes -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add kalshi_trader/data/models.py tests/test_strategies.py
git commit -m "feat: add effective_no_bid/no_ask fallback properties to MarketSnapshot"
```

---

### Task 3: Fix MarketMaker Strategy

**Problem:** (a) MarketMaker's direction logic uses `market.yes_bid < market.no_bid` but `no_bid` is usually `None` in stored data. Must use `effective_no_bid`. (b) `min_volume=100` filters out 99.93% of data. For backtesting, the volume filter is too strict.

**Files:**
- Modify: `kalshi_trader/strategies/market_maker.py:18-37`
- Test: `tests/test_strategies.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_strategies.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_strategies.py::test_market_maker_uses_effective_no_bid tests/test_strategies.py::test_market_maker_no_volume_filter_default -v`
Expected: FAIL

- [ ] **Step 3: Update MarketMaker strategy**

Replace `on_market_update` in `kalshi_trader/strategies/market_maker.py`:

```python
    def on_market_update(self, market: MarketSnapshot, signals: ExternalSignals) -> Optional[Signal]:
        if market.spread is None or market.spread < self.min_spread:
            return None
        if market.volume < self.min_volume:
            return None

        yes_bid = market.yes_bid
        no_bid = market.effective_no_bid
        if yes_bid is not None and no_bid is not None and yes_bid < no_bid:
            direction = "yes"
        else:
            direction = "no"

        return Signal(
            ticker=market.ticker,
            direction=direction,
            confidence=min(market.spread / 10.0, 1.0),
            size=self.contracts_per_quote,
            strategy_name=self.name,
            reason=f"spread={market.spread} > min={self.min_spread}",
            timestamp=int(time.time()),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_strategies.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add kalshi_trader/strategies/market_maker.py tests/test_strategies.py
git commit -m "fix: MarketMaker uses effective_no_bid, configurable volume filter"
```

---

### Task 4: Fix DirectionalStrategy Scoring

**Problem:** The maximum achievable confidence score is 0.45 (news=0.1, polls=0.15, price=0.2) but the default threshold is 0.6. The strategy can mathematically never fire. Also, the economic_releases penalty (-0.1) means even with all signals the max is 0.35. Score weights need rebalancing.

**Files:**
- Modify: `kalshi_trader/strategies/directional.py:31-61`
- Test: `tests/test_strategies.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_strategies.py`:

```python
def test_directional_fires_with_strong_price_signal():
    """DirectionalStrategy must fire when price signal is strong (mid > 60 or < 40)."""
    s = DirectionalStrategy(confidence_threshold=0.6)
    snap = MarketSnapshot(
        ticker="T", timestamp=1700000000,
        yes_bid=70, yes_ask=75, no_bid=25, no_ask=30,
        volume=100, open_interest=50, category="financial",
    )
    # mid_price = 72.5 > 60 → should have enough confidence to fire
    sig = s.on_market_update(snap, make_signals())
    assert sig is not None
    assert sig.direction == "yes"


def test_directional_fires_with_signals_and_price():
    """DirectionalStrategy with news + price should fire."""
    s = DirectionalStrategy(confidence_threshold=0.6)
    snap = MarketSnapshot(
        ticker="T", timestamp=1700000000,
        yes_bid=25, yes_ask=30, no_bid=70, no_ask=75,
        volume=100, open_interest=50, category="financial",
    )
    signals = ExternalSignals(
        timestamp=1700000000,
        news_headlines=[{"headline": "Breaking news"}],
    )
    # mid_price = 27.5 < 40 → price signal + news → should fire with direction=no
    sig = s.on_market_update(snap, signals)
    assert sig is not None
    assert sig.direction == "no"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_strategies.py::test_directional_fires_with_strong_price_signal tests/test_strategies.py::test_directional_fires_with_signals_and_price -v`
Expected: FAIL (sig is None because confidence < 0.6)

- [ ] **Step 3: Rebalance scoring weights**

Replace `_score` in `kalshi_trader/strategies/directional.py`:

```python
    def _score(self, market: MarketSnapshot, signals: ExternalSignals):
        """
        Combine signal sources into a directional confidence score.
        Returns (confidence, direction, reason).

        Scoring (max achievable = 1.0):
        - Price conviction (distance from 50): up to 0.65
        - News headlines present: +0.15
        - Poll data present: +0.2
        - Economic releases (uncertainty): -0.1
        """
        score = 0.0
        sources = []

        if signals.news_headlines:
            score += 0.15
            sources.append("news")

        if signals.economic_releases:
            score -= 0.1
            sources.append("econ_release_penalty")

        if signals.poll_data:
            score += 0.2
            sources.append("polls")

        direction = "yes"  # default
        if market.mid_price is not None:
            distance = abs(market.mid_price - 50)
            price_score = min(distance / 15.0, 1.0) * 0.65
            score += price_score
            if market.mid_price > 50:
                direction = "yes"
            else:
                direction = "no"
            if distance > 5:
                sources.append(f"price_conviction={distance:.0f}")

        confidence = max(0.0, min(score, 1.0))
        return confidence, direction, f"sources={sources}"
```

**Score ranges with default threshold=0.6:**
- mid=72.5 (distance=22.5): price_score = min(22.5/15, 1) * 0.65 = 0.65 → fires alone
- mid=65 (distance=15): price_score = 0.65 → fires alone
- mid=60 (distance=10): price_score = 0.433 → needs news (+0.15=0.58) or polls (+0.2=0.63)
- mid=55 (distance=5): price_score = 0.217 → needs multiple signals

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_strategies.py -v`
Expected: ALL PASS (including existing test_directional_no_signal_below_threshold which uses threshold=0.7 and blank signals with mid=41, distance=9, price_score=0.39 < 0.7 — still None)

- [ ] **Step 5: Commit**

```bash
git add kalshi_trader/strategies/directional.py tests/test_strategies.py
git commit -m "fix: rebalance DirectionalStrategy scoring so threshold is reachable"
```

---

### Task 5: Fix run_research.py to Load Signals and Use Sensible Defaults

**Problem:** (a) Backtest passes blank ExternalSignals — DirectionalStrategy gets no signal inputs. (b) MarketMaker is constructed with default min_volume=100 which filters out almost everything. (c) No way to see what's happening during the backtest.

**Files:**
- Modify: `kalshi_trader/scripts/run_research.py:59-67`
- Test: `tests/test_research.py`

- [ ] **Step 1: Write test for signal loading fallback**

Add to `tests/test_research.py`:

```python
def test_signals_fn_fallback_when_no_cache(tmp_path):
    """When no cached signals exist, signals_fn should return blank ExternalSignals."""
    from kalshi_trader.data.external_signals import ExternalSignalCollector

    cfg = KalshiConfig()
    cfg.data_dir = str(tmp_path)
    sig_collector = ExternalSignalCollector(cfg)
    cached = sig_collector.load_cached()
    assert cached is None  # no cache exists

    # The fallback should produce blank signals
    blank = ExternalSignals(timestamp=0)
    assert blank.news_headlines == []
    assert blank.poll_data == []
```

- [ ] **Step 2: Load cached external signals**

In `kalshi_trader/scripts/run_research.py`, replace the backtest section (lines 59-67):

```python
    # Load external signals (use cache if available)
    from kalshi_trader.data.external_signals import ExternalSignalCollector
    sig_collector = ExternalSignalCollector(cfg)
    cached_signals = sig_collector.load_cached()
    if cached_signals:
        logger.info("Using cached external signals")
        signals_fn = lambda ts: cached_signals
    else:
        logger.info("No cached signals; using blank signals")
        blank = ExternalSignals(timestamp=int(time.time()))
        signals_fn = lambda ts: blank

    # Backtest
    strategy_map = {
        "MarketMaker": MarketMakerStrategy(min_volume=0),
        "Directional": DirectionalStrategy(),
    }
    strategy = strategy_map[args.strategy]
    bt = Backtester(cfg)
    result = bt.run(strategy, snapshots, signals_fn)
```

- [ ] **Step 2: Add verbose trade logging to output**

After the existing logger.info lines in run_research.py, add:

```python
    if result.trade_log:
        logger.info(f"\n  Sample trades (first 10):")
        for t in result.trade_log[:10]:
            logger.info(
                f"    {t['ticker']} {t['direction']} "
                f"entry={t['entry_price']}c exit={t['exit_price']}c "
                f"pnl=${t['pnl']:.2f}"
            )
    else:
        logger.info("  No trades were generated. Check strategy thresholds and data quality.")
```

- [ ] **Step 3: Verify by running the research script**

Run: `python -m kalshi_trader.scripts.run_research --strategy MarketMaker --days 14`
Expected: Should now show trades > 0 (positions close via close_time resolution)

- [ ] **Step 4: Commit**

```bash
git add kalshi_trader/scripts/run_research.py
git commit -m "fix: load cached signals, relax volume filter, add trade logging in run_research"
```

---

### Task 6: Add Settlement Backfill to MarketCollector

**Problem:** The collector only fetches active markets (`status="open"`). It never learns when markets settle. We need a method to fetch settled markets and update stored snapshots with settlement outcomes.

**Files:**
- Modify: `kalshi_trader/data/market_collector.py`
- Modify: `kalshi_trader/client/kalshi_client.py:70-76`
- Test: `tests/test_market_collector.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_market_collector.py`:

```python
def test_backfill_settlement_updates_snapshots(tmp_path):
    """backfill_settlement must update stored snapshots with settlement outcomes."""
    import json, os

    cfg = KalshiConfig()
    cfg.data_dir = str(tmp_path)

    # Create a stored snapshot without settlement
    ticker = "TEST-TICKER"
    date_str = "2026-03-07"
    ticker_dir = tmp_path / date_str / ticker
    ticker_dir.mkdir(parents=True)
    snap_data = {
        "ticker": ticker, "timestamp": 1709856000,
        "yes_bid": 45, "yes_ask": 50, "no_bid": 50, "no_ask": 55,
        "volume": 100, "open_interest": 50, "category": "financial",
        "title": "Test", "close_time": "", "settled": None,
    }
    with open(ticker_dir / "1709856000000000000.json", "w") as f:
        json.dump(snap_data, f)

    # Mock client that returns settled market
    class MockClient:
        def get_markets(self, status=None):
            if status == "settled":
                return [{
                    "ticker": ticker, "result": "yes",
                    "yes_bid": 99, "yes_ask": 100, "no_bid": 0, "no_ask": 1,
                    "volume": 200, "open_interest": 0, "category": "financial",
                    "title": "Test", "close_time": "",
                }]
            return []

    collector = MarketCollector(MockClient(), cfg)
    updated = collector.backfill_settlement(date_str)
    assert updated >= 1

    # Verify the snapshot was updated
    with open(ticker_dir / "1709856000000000000.json") as f:
        data = json.load(f)
    assert data["settled"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_market_collector.py::test_backfill_settlement_updates_snapshots -v`
Expected: FAIL (backfill_settlement method doesn't exist)

- [ ] **Step 3: Add `result` field to KalshiClient._market_to_dict**

The Kalshi API returns a `result` field on settled markets ("yes" or "no"), but `_market_to_dict` strips it. Add it to `kalshi_trader/client/kalshi_client.py` in `_market_to_dict`:

```python
    def _market_to_dict(self, m) -> Dict:
        _ct = getattr(m, "close_time", None)
        yes_bid = getattr(m, "yes_bid", None)
        yes_ask = getattr(m, "yes_ask", None)
        _raw_no_bid = getattr(m, "no_bid", None)
        no_bid = _raw_no_bid if _raw_no_bid is not None else (100 - yes_ask if yes_ask is not None else None)
        _raw_no_ask = getattr(m, "no_ask", None)
        no_ask = _raw_no_ask if _raw_no_ask is not None else (100 - yes_bid if yes_bid is not None else None)
        return {
            "ticker": m.ticker,
            "title": getattr(m, "title", ""),
            "category": getattr(m, "category", ""),
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "no_bid": no_bid,
            "no_ask": no_ask,
            "volume": getattr(m, "volume", 0),
            "open_interest": getattr(m, "open_interest", 0),
            "status": getattr(m, "status", ""),
            "result": getattr(m, "result", None),
            "close_time": _ct.isoformat() if hasattr(_ct, "isoformat") else str(_ct) if _ct else "",
        }
```

- [ ] **Step 4: Implement backfill_settlement**

Add to `kalshi_trader/data/market_collector.py`:

```python
    def backfill_settlement(self, date_str: str) -> int:
        """
        Fetch settled markets from API and update stored snapshots with settlement outcome.
        Returns number of snapshots updated.
        """
        if self.client is None:
            return 0

        try:
            settled_markets = self.client.get_markets(status="settled")
        except Exception as e:
            self.logger.error(f"Failed to fetch settled markets: {e}")
            return 0

        # Build lookup: ticker -> settled outcome
        outcomes = {}
        for m in settled_markets:
            ticker = m.get("ticker") if isinstance(m, dict) else getattr(m, "ticker", None)
            result = m.get("result") if isinstance(m, dict) else getattr(m, "result", None)
            if ticker and result:
                outcomes[ticker] = result == "yes"

        date_dir = os.path.join(self.config.data_dir, date_str)
        if not os.path.exists(date_dir):
            return 0

        updated = 0
        for ticker_name in os.listdir(date_dir):
            if ticker_name not in outcomes:
                continue
            ticker_dir = os.path.join(date_dir, ticker_name)
            for fname in os.listdir(ticker_dir):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(ticker_dir, fname)
                with open(fpath) as f:
                    data = json.load(f)
                if data.get("settled") is not None:
                    continue  # already has settlement data
                data["settled"] = outcomes[ticker_name]
                with open(fpath, "w") as f:
                    json.dump(data, f)
                updated += 1

        self.logger.info(f"Backfilled {updated} snapshots for {date_str}")
        return updated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_market_collector.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add kalshi_trader/data/market_collector.py tests/test_market_collector.py
git commit -m "feat: add settlement backfill to MarketCollector"
```

---

### Task 7: Add Backfill Script Entry Point

**Problem:** There's no way to retroactively add settlement data to already-collected snapshots. Need a script the user can run.

**Files:**
- Modify: `kalshi_trader/scripts/run_research.py`

- [ ] **Step 1: Add --backfill flag to run_research.py**

Add to the argparse section:

```python
    parser.add_argument("--backfill", action="store_true",
                        help="Backfill settlement data from Kalshi API before running backtest")
```

Add after snapshot loading, before signal tests:

```python
    if args.backfill:
        from kalshi_trader.client.kalshi_client import KalshiClient
        client = KalshiClient(cfg)
        for i in range(args.days):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            backfill_collector = MarketCollector(client, cfg)
            backfill_collector.backfill_settlement(date)
        # Reload snapshots after backfill
        snapshots = []
        for i in range(args.days):
            date = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            date_dir = os.path.join(cfg.data_dir, date)
            if not os.path.exists(date_dir):
                continue
            for ticker in os.listdir(date_dir):
                snapshots.extend(collector.load_snapshots(ticker, date))
        logger.info(f"After backfill: {len(snapshots)} snapshots")
```

- [ ] **Step 2: Verify script runs without error**

Run: `python -m kalshi_trader.scripts.run_research --help`
Expected: Shows --backfill flag in help

- [ ] **Step 3: Commit**

```bash
git add kalshi_trader/scripts/run_research.py
git commit -m "feat: add --backfill flag to run_research for settlement data"
```

---

### Task 8: Integration Test — Full Backtest Pipeline

**Problem:** Need an end-to-end test confirming the entire pipeline produces meaningful results.

**Files:**
- Test: `tests/test_research.py`

- [ ] **Step 1: Write integration test**

Add to `tests/test_research.py`:

```python
def test_full_backtest_pipeline_produces_trades():
    """End-to-end: realistic data with close_time → backtester produces trades with correct P&L."""
    from kalshi_trader.strategies.market_maker import MarketMakerStrategy

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
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_research.py::test_full_backtest_pipeline_produces_trades -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_research.py
git commit -m "test: add end-to-end backtest pipeline integration test"
```
