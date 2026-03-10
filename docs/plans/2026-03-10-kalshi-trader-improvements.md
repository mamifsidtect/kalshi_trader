# Kalshi Trader Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 9 bugs, wire 3 disconnected features, and add 3 improvements to the kalshi_trader codebase.

**Architecture:** Changes are isolated to individual files. Each task is self-contained with its own test. No architectural redesign — just targeted fixes and wiring.

**Tech Stack:** Python 3.13, FastAPI, pytest, collections.deque, tempfile (stdlib), kalshi-python

**Run all tests with:** `cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -v`

---

### Task 1: Fix `no_bid`/`no_ask` in `_market_to_dict`

Kalshi is binary — `no_bid = 100 - yes_ask` and `no_ask = 100 - yes_bid`. Without this, every `MarketSnapshot` has `None` for NO-side prices, breaking `MarketMakerStrategy` direction logic and `ArbitrageStrategy`.

**Files:**
- Modify: `kalshi_trader/client/kalshi_client.py:129-141`
- Test: `tests/test_market_collector.py`

**Step 1: Write the failing test**

Add to `tests/test_market_collector.py`:

```python
def test_market_collector_derives_no_bid_no_ask(tmp_path):
    """_market_to_dict must populate no_bid and no_ask from YES prices."""
    cfg = KalshiConfig(data_dir=str(tmp_path))
    mock_client = MagicMock()
    mock_client.get_markets.return_value = [{
        "ticker": "TEST-2", "yes_bid": 40, "yes_ask": 45,
        "volume": 100, "open_interest": 50,
        "category": "financial", "title": "T", "close_time": "",
    }]
    collector = MarketCollector(mock_client, cfg)
    snapshots = collector.collect_once()
    assert snapshots[0].no_bid == 55   # 100 - yes_ask(45)
    assert snapshots[0].no_ask == 60   # 100 - yes_bid(40)
```

**Step 2: Run test to verify it fails**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_market_collector.py::test_market_collector_derives_no_bid_no_ask -v
```
Expected: FAIL — `no_bid` is `None`

**Step 3: Implement fix in `kalshi_client.py`**

In `_market_to_dict`, replace the return dict. After computing `yes_bid` and `yes_ask`, derive NO prices:

```python
def _market_to_dict(self, m) -> Dict:
    _ct = getattr(m, "close_time", None)
    yes_bid = getattr(m, "yes_bid", None)
    yes_ask = getattr(m, "yes_ask", None)
    no_bid = getattr(m, "no_bid", None) or (100 - yes_ask if yes_ask is not None else None)
    no_ask = getattr(m, "no_ask", None) or (100 - yes_bid if yes_bid is not None else None)
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
        "close_time": _ct.isoformat() if hasattr(_ct, "isoformat") else str(_ct) if _ct else "",
    }
```

**Step 4: Run test to verify it passes**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_market_collector.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/client/kalshi_client.py tests/test_market_collector.py && git commit -m "fix: derive no_bid/no_ask from YES prices in _market_to_dict"
```

---

### Task 2: Atomic cache write in `external_signals.py`

`_cache` uses a plain `open(path, "w")` write. If interrupted it leaves a corrupt file. `market_collector.py` already has the correct `tempfile.mkstemp` + `os.replace` pattern — apply it here.

**Files:**
- Modify: `kalshi_trader/data/external_signals.py:98-105`
- Test: `tests/test_external_signals.py`

**Step 1: Write the failing test**

Add to `tests/test_external_signals.py`:

```python
def test_cache_is_loadable_after_write(tmp_path):
    """Cached signals must be readable back via load_cached."""
    from unittest.mock import patch
    cfg = KalshiConfig(data_dir=str(tmp_path))
    collector = ExternalSignalCollector(cfg)
    with patch.object(collector, "_fetch_economic_releases", return_value=[{"id": "CPI"}]):
        with patch.object(collector, "_fetch_news", return_value=[]):
            with patch.object(collector, "_fetch_polls", return_value=[]):
                collector.collect()
    loaded = collector.load_cached()
    assert loaded is not None
    assert loaded.economic_releases == [{"id": "CPI"}]
```

**Step 2: Run test to verify it fails**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_external_signals.py::test_cache_is_loadable_after_write -v
```
Expected: FAIL — `load_cached` returns `None` or data doesn't match (the existing non-atomic write may pass, but we want to confirm the pattern change)

> Note: the test might already pass with the non-atomic write. That's fine — the point is to confirm behavior is preserved after refactoring. Run it first to establish baseline, then refactor and confirm it still passes.

**Step 3: Implement atomic write in `external_signals.py`**

Replace the `_cache` method:

```python
def _cache(self, signals: ExternalSignals):
    import tempfile
    data = json.dumps({
        "timestamp": signals.timestamp,
        "economic_releases": signals.economic_releases,
        "news_headlines": signals.news_headlines,
        "poll_data": signals.poll_data,
    }).encode()
    fd, tmp_path = tempfile.mkstemp(dir=self.config.data_dir, suffix=".tmp")
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.replace(tmp_path, self._cache_path)
```

**Step 4: Run all external signal tests**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_external_signals.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/data/external_signals.py tests/test_external_signals.py && git commit -m "fix: use atomic write in external_signals cache"
```

---

### Task 3: Guard against overwriting open positions in `PaperTrader`

`execute` silently overwrites `self._positions[signal.ticker]` if called twice for the same ticker. The original entry is lost.

**Files:**
- Modify: `kalshi_trader/execution/paper_trader.py:19-41`
- Test: `tests/test_execution.py`

**Step 1: Write the failing test**

Add to `tests/test_execution.py`:

```python
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
```

**Step 2: Run test to verify it fails**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_execution.py::test_paper_trader_does_not_overwrite_open_position -v
```
Expected: FAIL — second execute silently overwrites, entry_price becomes 50

**Step 3: Implement guard in `paper_trader.py`**

At the top of `execute`, before computing `cost`:

```python
def execute(self, signal: Signal, current_price: int) -> Dict[str, Any]:
    if signal.ticker in self._positions:
        self.logger.warning(
            f"[PAPER] Position already open for {signal.ticker}; skipping duplicate order"
        )
        return {"status": "rejected", "reason": "position already open", "ticker": signal.ticker}
    cost = signal.size * (current_price / 100.0)
    # ... rest unchanged
```

**Step 4: Run all execution tests**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_execution.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/execution/paper_trader.py tests/test_execution.py && git commit -m "fix: reject duplicate open positions in PaperTrader"
```

---

### Task 4: Replace O(n) `SIGNAL_FEED` list with `deque`

`SIGNAL_FEED.pop(0)` in the trading loop is O(n). Replace with `collections.deque(maxlen=200)` — the `maxlen` cap is automatic, no manual pop needed.

**Files:**
- Modify: `kalshi_trader/scripts/run_live.py:22, 51-53`

> No new test needed — this is a performance fix with identical observable behavior. The existing signal feed behavior is tested implicitly through the web route tests.

**Step 1: Apply the change in `run_live.py`**

Change line 22 from:
```python
SIGNAL_FEED = []
```
to:
```python
from collections import deque
SIGNAL_FEED = deque(maxlen=200)
```

Remove lines 52-53 (the manual length check and pop):
```python
# DELETE these two lines:
if len(SIGNAL_FEED) > 200:
    SIGNAL_FEED.pop(0)
```

The `SIGNAL_FEED.append(feed_entry)` line stays — `deque` handles the cap automatically.

**Step 2: Verify existing tests still pass**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -v
```
Expected: All PASS

**Step 3: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/scripts/run_live.py && git commit -m "fix: replace O(n) SIGNAL_FEED list with deque(maxlen=200)"
```

---

### Task 5: Fix backtester ticker mixing

The backtester iterates a flat list of snapshots from multiple tickers. A position opened on `TICKER-A` can be closed by `TICKER-B`'s `settled` field. Fix: group snapshots by ticker, simulate each independently, merge results.

**Files:**
- Modify: `kalshi_trader/research/backtester.py:32-82`
- Test: `tests/test_research.py`

**Step 1: Write the failing test**

Add to `tests/test_research.py`:

```python
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
    # TICKER-B: 3 snapshots, settles NO — should not affect TICKER-A position
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
```

**Step 2: Run test to verify it fails**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_research.py::test_backtester_does_not_mix_tickers -v
```
Expected: FAIL — interleaved tickers corrupt the result

**Step 3: Fix `backtester.py` `run` method**

Replace the `run` method body to group by ticker:

```python
def run(
    self,
    strategy: BaseStrategy,
    snapshots: List[MarketSnapshot],
    signals_fn: Callable[[int], ExternalSignals],
    slippage: Optional[int] = None,
) -> BacktestResult:
    slippage = slippage if slippage is not None else self.SLIPPAGE_CENTS

    # Group snapshots by ticker to avoid cross-ticker contamination
    by_ticker: Dict[str, List[MarketSnapshot]] = {}
    for snap in snapshots:
        by_ticker.setdefault(snap.ticker, []).append(snap)

    all_trades: List[Dict] = []
    all_pnl: List[float] = []

    for ticker_snaps in by_ticker.values():
        trades, pnl = self._run_single_ticker(strategy, ticker_snaps, signals_fn, slippage)
        all_trades.extend(trades)
        all_pnl.extend(pnl)

    return self._compute_result(strategy.name, all_trades, all_pnl)

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
        signal = strategy.on_market_update(snap, signals)

        if open_position is None and signal is not None and snap.mid_price is not None:
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

        elif open_position is not None and snap.settled is not None:
            exit_price = 99 if snap.settled else 1
            entry = open_position["entry_price"]
            if open_position["direction"] == "yes":
                pnl = open_position["size"] * ((exit_price - entry) / 100.0)
            else:
                pnl = open_position["size"] * ((entry - exit_price) / 100.0)

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

    return trade_log, pnl_series
```

Also add `Dict` to the imports at the top of `backtester.py` if not already present (it's already there).

**Step 4: Run all research tests**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_research.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/research/backtester.py tests/test_research.py && git commit -m "fix: group backtester snapshots by ticker to prevent cross-ticker contamination"
```

---

### Task 6: Add category exposure enforcement to `RiskManager`

`max_category_exposure_pct` is in config but `validate()` never checks it. Also `record_open_position` needs to accept a `category` param so we can enforce per-category limits.

**Files:**
- Modify: `kalshi_trader/risk/risk_manager.py`
- Test: `tests/test_risk_manager.py`

**Step 1: Write the failing test**

Add to `tests/test_risk_manager.py`:

```python
def test_signal_rejected_over_category_exposure():
    cfg = KalshiConfig(max_category_exposure_pct=0.10)
    rm = RiskManager(cfg, bankroll=1000.0)
    # Record $105 exposure in "financial" category (10.5% of $1000)
    rm.record_open_position("OTHER-1", exposure=105.0, category="financial")
    sig = make_signal()  # make_signal uses direction="yes", no category on Signal
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
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_risk_manager.py::test_signal_rejected_over_category_exposure tests/test_risk_manager.py::test_different_category_not_blocked -v
```
Expected: FAIL — `validate` doesn't accept `category` kwarg yet

**Step 3: Update `risk_manager.py`**

Change `_open_positions` to store `(exposure, category)` tuples. Update `record_open_position` and `validate`:

```python
from typing import Dict, Optional, Tuple
from kalshi_trader.config import KalshiConfig
from kalshi_trader.data.models import Signal
from kalshi_trader.utils.logger import get_logger


class RiskManager:
    def __init__(self, config: KalshiConfig, bankroll: float):
        self.config = config
        self.bankroll = bankroll
        self.logger = get_logger(__name__, config.log_level)
        self._daily_loss: float = 0.0
        self._halted: bool = False
        self._open_positions: Dict[str, Tuple[float, str]] = {}  # ticker -> (exposure, category)

    def validate(self, signal: Signal, current_price: int, category: str = "") -> Tuple[bool, str]:
        if self._halted:
            return False, "trading halted: daily loss limit reached"

        if self._daily_loss >= self.bankroll * self.config.daily_loss_limit_pct:
            self._halted = True
            return False, f"daily loss limit reached (${self._daily_loss:.2f})"

        total_exposure = sum(exp for exp, _ in self._open_positions.values())
        max_exposure = self.bankroll * self.config.max_total_exposure_pct
        if total_exposure >= max_exposure:
            return False, f"max total exposure reached (${total_exposure:.2f} >= ${max_exposure:.2f})"

        if category:
            cat_exposure = sum(
                exp for exp, cat in self._open_positions.values() if cat == category
            )
            max_cat = self.bankroll * self.config.max_category_exposure_pct
            if cat_exposure >= max_cat:
                return False, f"category '{category}' exposure limit reached (${cat_exposure:.2f} >= ${max_cat:.2f})"

        return True, "ok"

    def size_position(self, current_price: int) -> int:
        if current_price <= 0:
            return 0
        max_dollars = self.bankroll * self.config.max_position_pct
        cost_per_contract = current_price / 100.0
        return max(1, int(max_dollars / cost_per_contract))

    def record_daily_loss(self, amount: float):
        self._daily_loss += amount
        if self._daily_loss >= self.bankroll * self.config.daily_loss_limit_pct:
            self._halted = True
            self.logger.warning(f"Daily loss limit reached: ${self._daily_loss:.2f}")

    def record_open_position(self, ticker: str, exposure: float, category: str = ""):
        self._open_positions[ticker] = (exposure, category)

    def close_position(self, ticker: str):
        self._open_positions.pop(ticker, None)

    def reset_daily(self):
        self._daily_loss = 0.0
        self._halted = False
        self.logger.info("Daily risk counters reset")
```

**Step 4: Run all risk manager tests**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_risk_manager.py -v
```
Expected: All PASS

> Note: existing tests call `validate(sig, current_price)` without `category` — the default `category=""` means the category check is skipped, so they remain unaffected.

**Step 5: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/risk/risk_manager.py tests/test_risk_manager.py && git commit -m "feat: enforce max_category_exposure_pct in RiskManager"
```

---

### Task 7: Fix `live_trader.close_position` wrong side

When closing a position, the code uses the same `side` and `action="buy"` — this opens another position instead of exiting. Should use `action="sell"` with the same side. Also remove the hardcoded `price=99`.

**Files:**
- Modify: `kalshi_trader/execution/live_trader.py:31-46`
- Test: `tests/test_execution.py`

**Step 1: Write the failing test**

Add to `tests/test_execution.py`:

```python
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
    assert call_kwargs.kwargs.get("action") == "sell" or (
        call_kwargs.args and "sell" in str(call_kwargs)
    )
```

**Step 2: Run test to verify it fails**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_execution.py::test_live_trader_close_uses_sell_action -v
```
Expected: FAIL — current code uses `action="buy"`

**Step 3: Fix `live_trader.py` `close_position`**

```python
def close_position(self, ticker: str) -> bool:
    try:
        positions = self.client.get_positions()
        matched = [p for p in positions if p["ticker"] == ticker]
        if not matched:
            self.logger.warning(f"[LIVE] No open position found for {ticker}")
            return False
        for pos in matched:
            self.client.place_order(
                ticker=ticker,
                side=pos["side"],
                action="sell",
                count=pos["quantity"],
            )
        return True
    except Exception as e:
        self.logger.error(f"[LIVE] Failed to close {ticker}: {e}")
        return False
```

Note: `price` is removed — Kalshi's `CreateOrderRequest` for a sell can use a market order type or the caller can handle price separately. This removes the hardcoded `price=99`.

**Step 4: Run all execution tests**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_execution.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/execution/live_trader.py tests/test_execution.py && git commit -m "fix: use action=sell in live_trader close_position"
```

---

### Task 8: Wire risk manager fully into trading loop

Three things at once in `run_live.py`: (a) fix entry price for "no" direction, (b) record open positions + call `size_position` after approval, (c) daily reset at loop top.

**Files:**
- Modify: `kalshi_trader/scripts/run_live.py:25-64`

> This is script logic — no unit test needed. Verify with a dry-run import check.

**Step 1: Apply all three wiring changes to `trading_loop` in `run_live.py`**

```python
from datetime import datetime, timezone

def trading_loop(cfg, client, risk_manager, logger):
    market_collector = MarketCollector(client, cfg)
    signal_collector = ExternalSignalCollector(cfg)
    strategies = [MarketMakerStrategy(), DirectionalStrategy()]
    last_reset_date = datetime.now(timezone.utc).date()

    while True:
        try:
            # Daily reset check
            today = datetime.now(timezone.utc).date()
            if today > last_reset_date:
                risk_manager.reset_daily()
                last_reset_date = today

            snapshots = market_collector.collect_once()
            ext_signals = signal_collector.collect()

            for snap in snapshots:
                for strategy in strategies:
                    signal = strategy.on_market_update(snap, ext_signals)
                    if signal is None:
                        continue

                    # Use correct side price
                    if signal.direction == "yes":
                        entry_price = snap.yes_ask or 50
                    else:
                        entry_price = snap.no_ask or 50

                    approved, reason = risk_manager.validate(
                        signal, current_price=entry_price, category=snap.category
                    )
                    feed_entry = {
                        "ticker": signal.ticker,
                        "direction": signal.direction,
                        "confidence": signal.confidence,
                        "strategy": signal.strategy_name,
                        "reason": reason,
                        "approved": approved,
                    }
                    SIGNAL_FEED.append(feed_entry)

                    if approved:
                        # Size position from risk manager
                        signal.size = risk_manager.size_position(entry_price)
                        result = executor.execute(signal, current_price=entry_price)
                        if result.get("status") not in ("rejected",):
                            cost = signal.size * (entry_price / 100.0)
                            risk_manager.record_open_position(
                                signal.ticker, cost, category=snap.category
                            )

        except KeyboardInterrupt:
            logger.info("Trading loop stopped by user")
            break
        except Exception as e:
            logger.error(f"Trading loop error: {e}")

        time.sleep(cfg.collection_interval_seconds)
```

Note: `executor` needs to be passed in. Update the function signature to `trading_loop(cfg, client, risk_manager, executor, logger)` — it already has this signature, just confirming no change needed there.

Also add `from datetime import datetime, timezone` at the top of the file if not already imported.

**Step 2: Verify the script is importable**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -c "from kalshi_trader.scripts.run_live import trading_loop; print('ok')"
```
Expected: `ok`

**Step 3: Run full test suite to catch regressions**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -v
```
Expected: All PASS

**Step 4: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/scripts/run_live.py && git commit -m "fix: correct entry price for no-direction trades, wire size_position and daily reset"
```

---

### Task 9: Wire `ArbitrageStrategy` into `run_live.py`

`ArbitrageStrategy` exists, is tested, but never runs. Add it to the strategies list and add a `_update_correlated_prices` helper that populates it from poll data.

**Files:**
- Modify: `kalshi_trader/scripts/run_live.py`

**Step 1: Add imports and helper function**

At the top of `run_live.py`, add:
```python
from kalshi_trader.strategies.arbitrage import ArbitrageStrategy
```

Add this helper function before `trading_loop`:

```python
def _update_correlated_prices(arb_strategy: ArbitrageStrategy, ext_signals):
    """
    Populate ArbitrageStrategy with external probabilities from poll data.
    Each poll entry with a 'kalshi_ticker' key and 'community_prediction' float
    is registered as a correlated price. This is a hook — extend as needed.
    """
    for poll in ext_signals.poll_data:
        ticker = poll.get("kalshi_ticker")
        prob = poll.get("community_prediction")
        if ticker and isinstance(prob, (int, float)):
            arb_strategy.set_correlated_price(ticker, float(prob))
```

**Step 2: Add `ArbitrageStrategy` to strategies list in `trading_loop`**

Change:
```python
strategies = [MarketMakerStrategy(), DirectionalStrategy()]
```
to:
```python
arb_strategy = ArbitrageStrategy()
strategies = [MarketMakerStrategy(), DirectionalStrategy(), arb_strategy]
```

And inside the loop, after `ext_signals = signal_collector.collect()`, add:
```python
_update_correlated_prices(arb_strategy, ext_signals)
```

**Step 3: Verify importable and tests pass**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -c "from kalshi_trader.scripts.run_live import trading_loop; print('ok')"
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -v
```
Expected: `ok` and all PASS

**Step 4: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/scripts/run_live.py && git commit -m "feat: wire ArbitrageStrategy into trading loop with correlated price hook"
```

---

### Task 10: Add `get_live_mid_price` to `DataService`

`KalshiClient.get_orderbook()` exists but is never used. Add a `get_live_mid_price(client, ticker)` method to `DataService` that gives a fresh mid-price from the live orderbook. Wire it into `run_live.py` as the preferred entry price.

**Files:**
- Modify: `kalshi_trader/web/services/data_service.py`
- Modify: `kalshi_trader/scripts/run_live.py`
- Test: `tests/test_web.py`

**Step 1: Write the failing test**

Read `tests/test_web.py` first to understand the existing pattern, then add:

```python
def test_data_service_get_live_mid_price():
    from unittest.mock import MagicMock
    from kalshi_trader.web.services.data_service import DataService
    from kalshi_trader.config import KalshiConfig

    cfg = KalshiConfig()
    svc = DataService(cfg)
    mock_client = MagicMock()
    mock_client.get_orderbook.return_value = {
        "yes": [[45, 10], [44, 5]],  # best yes bid = 45
        "no":  [[55, 10], [54, 5]],  # best no bid = 55 → yes ask = 45
    }
    mid = svc.get_live_mid_price(mock_client, "TEST-1")
    # best yes bid=45, best yes ask = 100 - best no bid(55) = 45 → mid = 45.0
    assert mid == 45.0
```

**Step 2: Run test to verify it fails**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_web.py::test_data_service_get_live_mid_price -v
```
Expected: FAIL — `get_live_mid_price` not defined

**Step 3: Implement `get_live_mid_price` in `data_service.py`**

Add this method to `DataService`:

```python
def get_live_mid_price(self, client, ticker: str) -> Optional[float]:
    """
    Fetch live orderbook and return best-bid/best-ask mid price.
    Returns None if orderbook is unavailable or empty.
    """
    try:
        ob = client.get_orderbook(ticker)
        yes_levels = ob.get("yes", [])
        no_levels = ob.get("no", [])
        best_yes_bid = yes_levels[0][0] if yes_levels else None
        best_no_bid = no_levels[0][0] if no_levels else None
        # yes_ask = 100 - best_no_bid (Kalshi binary complement)
        yes_ask = (100 - best_no_bid) if best_no_bid is not None else None
        if best_yes_bid is not None and yes_ask is not None:
            return (best_yes_bid + yes_ask) / 2.0
        return None
    except Exception:
        return None
```

**Step 4: Wire into `run_live.py`**

In `trading_loop`, pass a `data_service` reference or the client directly. Since `client` is available in the loop, use it directly. Replace the entry price block:

```python
# Use live orderbook mid if available, else fall back to snapshot
from kalshi_trader.web.services.data_service import DataService
_ds = DataService(cfg)

# ... inside the loop, replace entry price logic:
live_mid = _ds.get_live_mid_price(client, snap.ticker)
if signal.direction == "yes":
    entry_price = int(live_mid) if live_mid else (snap.yes_ask or 50)
else:
    entry_price = int(100 - live_mid) if live_mid else (snap.no_ask or 50)
```

> Note: instantiate `_ds = DataService(cfg)` once before the `while True` loop, not inside it.

**Step 5: Run all tests**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -v
```
Expected: All PASS

**Step 6: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/web/services/data_service.py kalshi_trader/scripts/run_live.py tests/test_web.py && git commit -m "feat: add get_live_mid_price to DataService, use live orderbook for entry price"
```

---

## Final Verification

Run the full test suite one last time:

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -v --tb=short
```

All tests should pass. Then verify the main scripts are importable:

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -c "
from kalshi_trader.scripts.run_live import main
from kalshi_trader.scripts.collect_data import main
from kalshi_trader.scripts.run_research import main
print('all imports ok')
"
```

---

## Summary of Changes

| Task | File(s) | Type |
|------|---------|------|
| 1 | `client/kalshi_client.py` | Bug fix |
| 2 | `data/external_signals.py` | Bug fix |
| 3 | `execution/paper_trader.py` | Bug fix |
| 4 | `scripts/run_live.py` | Bug fix (perf) |
| 5 | `research/backtester.py` | Bug fix |
| 6 | `risk/risk_manager.py` | Feature wiring |
| 7 | `execution/live_trader.py` | Bug fix |
| 8 | `scripts/run_live.py` | Bug fix + wiring |
| 9 | `scripts/run_live.py` | Feature wiring |
| 10 | `web/services/data_service.py`, `scripts/run_live.py` | Addition |
