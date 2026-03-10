# Exit Signals + Polymarket Price Feed Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add strategy-driven position exits (settlement, price target, time limit) and a Polymarket price feed that populates `ArbitrageStrategy` with real external probabilities.

**Architecture:** Feature 1 adds `PositionMeta` to `RiskManager`, `on_exit()` to `BaseStrategy`, and an exit-checking loop in `run_live.py`. Feature 2 adds a `PolymarketClient`, a user-maintained JSON mapping file, and threads Polymarket probabilities through `ExternalSignals.correlated_prices` into `ArbitrageStrategy`.

**Tech Stack:** Python 3.13, requests, pytest, Polymarket Gamma API (`https://gamma-api.polymarket.com`)

**Run all tests with:** `cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -v`

---

### Task 1: Add `PositionMeta` and update `RiskManager`

`RiskManager._open_positions` currently stores `(exposure, category)` tuples. We need to store richer metadata: `entry_price`, `entry_ts`, `direction`, and `strategy_name` to support exit logic. All new fields are optional with safe defaults so existing tests keep working.

**Files:**
- Modify: `kalshi_trader/risk/risk_manager.py`
- Test: `tests/test_risk_manager.py`

**Step 1: Write the failing tests**

Add to `tests/test_risk_manager.py`:

```python
def test_position_meta_stored_and_retrievable():
    import time
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
```

**Step 2: Run to verify they fail**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_risk_manager.py::test_position_meta_stored_and_retrievable tests/test_risk_manager.py::test_has_position_false_when_absent tests/test_risk_manager.py::test_close_position_removes_meta -v
```
Expected: FAIL — `has_position` and `get_position_meta` not defined, `record_open_position` doesn't accept new kwargs

**Step 3: Implement `PositionMeta` and updated `RiskManager`**

Replace the entire `kalshi_trader/risk/risk_manager.py`:

```python
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from kalshi_trader.config import KalshiConfig
from kalshi_trader.data.models import Signal
from kalshi_trader.utils.logger import get_logger


@dataclass
class PositionMeta:
    exposure: float
    category: str = ""
    entry_price: int = 0
    entry_ts: int = 0
    direction: str = "yes"
    strategy_name: str = ""


class RiskManager:
    def __init__(self, config: KalshiConfig, bankroll: float):
        self.config = config
        self.bankroll = bankroll
        self.logger = get_logger(__name__, config.log_level)
        self._daily_loss: float = 0.0
        self._halted: bool = False
        self._open_positions: Dict[str, PositionMeta] = {}

    def validate(self, signal: Signal, current_price: int, category: str = "") -> Tuple[bool, str]:
        if self._halted:
            return False, "trading halted: daily loss limit reached"

        if self._daily_loss >= self.bankroll * self.config.daily_loss_limit_pct:
            self._halted = True
            return False, f"daily loss limit reached (${self._daily_loss:.2f})"

        total_exposure = sum(m.exposure for m in self._open_positions.values())
        max_exposure = self.bankroll * self.config.max_total_exposure_pct
        if total_exposure >= max_exposure:
            return False, f"max total exposure reached (${total_exposure:.2f} >= ${max_exposure:.2f})"

        if category:
            cat_exposure = sum(
                m.exposure for m in self._open_positions.values() if m.category == category
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

    def record_open_position(
        self,
        ticker: str,
        exposure: float,
        category: str = "",
        entry_price: int = 0,
        entry_ts: int = 0,
        direction: str = "yes",
        strategy_name: str = "",
    ):
        self._open_positions[ticker] = PositionMeta(
            exposure=exposure,
            category=category,
            entry_price=entry_price,
            entry_ts=entry_ts,
            direction=direction,
            strategy_name=strategy_name,
        )

    def has_position(self, ticker: str) -> bool:
        return ticker in self._open_positions

    def get_position_meta(self, ticker: str) -> Optional[PositionMeta]:
        return self._open_positions.get(ticker)

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
Expected: All 9 tests PASS (6 old + 3 new)

> Note: existing tests call `record_open_position("OTHER-1", exposure=105.0, category="financial")` — the new kwargs all have defaults so this keeps working.

**Step 5: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/risk/risk_manager.py tests/test_risk_manager.py && git commit -m "feat: add PositionMeta to RiskManager with has_position and get_position_meta"
```

---

### Task 2: Add `on_exit` to `BaseStrategy` and exit params to concrete strategies

`BaseStrategy` gets a concrete `on_exit` method with a default implementation using configurable `exit_profit_cents` and `exit_time_hours`. Each concrete strategy gains these params in `__init__`. Setting either to `0` disables that check.

**Files:**
- Modify: `kalshi_trader/strategies/base_strategy.py`
- Modify: `kalshi_trader/strategies/market_maker.py`
- Modify: `kalshi_trader/strategies/directional.py`
- Modify: `kalshi_trader/strategies/arbitrage.py`
- Test: `tests/test_strategies.py`

**Step 1: Write the failing tests**

Add to `tests/test_strategies.py`:

```python
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
    """on_exit for NO direction: profit when YES price falls."""
    s = MarketMakerStrategy(exit_profit_cents=10)
    # Entry (NO) at entry_price=58 (YES was 42), current YES mid=30 → NO profit = 58-30=28 >= 10
    snap = MarketSnapshot(
        ticker="T", timestamp=int(time.time()),
        yes_bid=28, yes_ask=32, no_bid=68, no_ask=72,
        volume=100, open_interest=50, category="financial"
    )
    assert s.on_exit(entry_price=58, entry_ts=int(time.time()), direction="no",
                     market=snap, signals=make_signals()) is True
```

**Step 2: Run to verify they fail**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_strategies.py::test_on_exit_profit_target_yes tests/test_strategies.py::test_on_exit_time_limit -v
```
Expected: FAIL — `on_exit` not defined, `exit_profit_cents` not accepted

**Step 3: Update `base_strategy.py`**

```python
import time as _time
from abc import ABC, abstractmethod
from typing import Optional
from kalshi_trader.data.models import MarketSnapshot, ExternalSignals, Signal


class BaseStrategy(ABC):
    name: str = "BaseStrategy"
    enabled: bool = True
    exit_profit_cents: int = 0
    exit_time_hours: int = 0

    @abstractmethod
    def on_market_update(
        self,
        market: MarketSnapshot,
        signals: ExternalSignals,
    ) -> Optional[Signal]:
        """Return a Signal to act on this market, or None to skip."""
        ...

    def on_exit(
        self,
        entry_price: int,
        entry_ts: int,
        direction: str,
        market: MarketSnapshot,
        signals: ExternalSignals,
    ) -> bool:
        """Return True to close this position early. Checks profit target and time limit."""
        if self.exit_profit_cents > 0 and market.mid_price is not None:
            if direction == "yes":
                profit = market.mid_price - entry_price
            else:
                profit = entry_price - market.mid_price
            if profit >= self.exit_profit_cents:
                return True
        if self.exit_time_hours > 0:
            elapsed_hours = (_time.time() - entry_ts) / 3600
            if elapsed_hours >= self.exit_time_hours:
                return True
        return False
```

**Step 4: Add `exit_profit_cents` and `exit_time_hours` to each concrete strategy**

`kalshi_trader/strategies/market_maker.py` — update `__init__`:

```python
def __init__(self, min_spread: int = 3, min_volume: int = 100, contracts_per_quote: int = 1,
             exit_profit_cents: int = 0, exit_time_hours: int = 0):
    self.min_spread = min_spread
    self.min_volume = min_volume
    self.contracts_per_quote = contracts_per_quote
    self.exit_profit_cents = exit_profit_cents
    self.exit_time_hours = exit_time_hours
```

`kalshi_trader/strategies/directional.py` — update `__init__`:

```python
def __init__(self, confidence_threshold: float = 0.6, contracts: int = 1,
             exit_profit_cents: int = 0, exit_time_hours: int = 0):
    self.confidence_threshold = confidence_threshold
    self.contracts = contracts
    self.exit_profit_cents = exit_profit_cents
    self.exit_time_hours = exit_time_hours
```

`kalshi_trader/strategies/arbitrage.py` — update `__init__`:

```python
def __init__(self, min_edge: float = 0.05, contracts: int = 1,
             exit_profit_cents: int = 0, exit_time_hours: int = 0):
    self.min_edge = min_edge
    self.contracts = contracts
    self.exit_profit_cents = exit_profit_cents
    self.exit_time_hours = exit_time_hours
    self._correlated_prices: Dict[str, float] = {}
```

**Step 5: Run all strategy tests**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_strategies.py -v
```
Expected: All PASS (existing 5 + new 5)

**Step 6: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/strategies/base_strategy.py kalshi_trader/strategies/market_maker.py kalshi_trader/strategies/directional.py kalshi_trader/strategies/arbitrage.py tests/test_strategies.py && git commit -m "feat: add on_exit to BaseStrategy with profit target and time limit"
```

---

### Task 3: Add exit and Polymarket config fields

Add `exit_profit_cents`, `exit_time_hours`, and `ticker_mappings_file` to `KalshiConfig` with env var loading.

**Files:**
- Modify: `kalshi_trader/config.py`

No new test needed — config changes are verified by import check and existing tests.

**Step 1: Add fields to `KalshiConfig` dataclass**

In `kalshi_trader/config.py`, add to `KalshiConfig` after the risk section:

```python
# Exit conditions
exit_profit_cents: int = 0    # 0 = disabled; close position when profit >= N cents
exit_time_hours: int = 0      # 0 = disabled; close position after N hours

# Polymarket integration
ticker_mappings_file: str = ""  # path to JSON: {kalshi_ticker: polymarket_condition_id}
```

In `load_config()`, add loading for these three env vars (after the existing ones):

```python
if os.getenv("EXIT_PROFIT_CENTS"):
    cfg.exit_profit_cents = int(os.getenv("EXIT_PROFIT_CENTS"))
if os.getenv("EXIT_TIME_HOURS"):
    cfg.exit_time_hours = int(os.getenv("EXIT_TIME_HOURS"))
if os.getenv("TICKER_MAPPINGS_FILE"):
    cfg.ticker_mappings_file = os.getenv("TICKER_MAPPINGS_FILE")
```

**Step 2: Verify importable**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -c "from kalshi_trader.config import load_config; cfg = load_config(); print(cfg.exit_profit_cents, cfg.exit_time_hours, cfg.ticker_mappings_file)"
```
Expected: `0 0 ` (empty string for file path)

**Step 3: Run full test suite**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -q --tb=no
```
Expected: All 54 tests PASS (49 existing + 5 new strategy tests from Task 2 + ... actually 49 + new ones so far)

**Step 4: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/config.py && git commit -m "feat: add exit_profit_cents, exit_time_hours, ticker_mappings_file to KalshiConfig"
```

---

### Task 4: Add `correlated_prices` to `ExternalSignals`

Add a `correlated_prices: Dict[str, float]` field to the `ExternalSignals` dataclass. This is the data bus between `ExternalSignalCollector` (which fetches Polymarket prices) and `ArbitrageStrategy` (which consumes them).

**Files:**
- Modify: `kalshi_trader/data/models.py`
- Test: `tests/test_market_collector.py` (or add to `test_external_signals.py`)

**Step 1: Write the failing test**

Add to `tests/test_external_signals.py`:

```python
def test_external_signals_has_correlated_prices_field():
    """ExternalSignals must have a correlated_prices dict field."""
    from kalshi_trader.data.models import ExternalSignals
    sig = ExternalSignals(timestamp=12345)
    assert hasattr(sig, "correlated_prices")
    assert isinstance(sig.correlated_prices, dict)
    # Can be populated
    sig.correlated_prices["KXTEST-1"] = 0.65
    assert sig.correlated_prices["KXTEST-1"] == 0.65
```

**Step 2: Run to verify it fails**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_external_signals.py::test_external_signals_has_correlated_prices_field -v
```
Expected: FAIL — `ExternalSignals` has no `correlated_prices`

**Step 3: Add field to `ExternalSignals` in `models.py`**

In `kalshi_trader/data/models.py`, update the `ExternalSignals` dataclass:

```python
@dataclass
class ExternalSignals:
    timestamp: int
    economic_releases: List[Dict] = field(default_factory=list)
    news_headlines: List[Dict] = field(default_factory=list)
    poll_data: List[Dict] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)
    correlated_prices: Dict[str, float] = field(default_factory=dict)
```

**Step 4: Run all tests**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -q --tb=no
```
Expected: All PASS

**Step 5: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/data/models.py tests/test_external_signals.py && git commit -m "feat: add correlated_prices field to ExternalSignals"
```

---

### Task 5: Create `PolymarketClient`

New class that fetches YES probabilities from the Polymarket Gamma API by condition ID. Condition IDs are hex strings like `"0xabc123..."`. The Gamma API returns a list of market objects; each has `outcomePrices` — a JSON-encoded string array where index 0 is YES probability.

**Files:**
- Create: `kalshi_trader/data/polymarket_client.py`
- Test: `tests/test_polymarket.py` (new file)

**Step 1: Write the failing tests**

Create `tests/test_polymarket.py`:

```python
from unittest.mock import patch, MagicMock
from kalshi_trader.data.polymarket_client import PolymarketClient


def test_get_probabilities_parses_outcome_prices():
    """get_probabilities returns float YES probability from outcomePrices."""
    client = PolymarketClient()
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [
        {"condition_id": "0xabc", "outcomePrices": '["0.65", "0.35"]'}
    ]
    with patch("kalshi_trader.data.polymarket_client.requests.get", return_value=mock_resp):
        result = client.get_probabilities(["0xabc"])
    assert result == {"0xabc": 0.65}


def test_get_probabilities_handles_list_outcome_prices():
    """outcomePrices can be a list (not just a JSON string)."""
    client = PolymarketClient()
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = [
        {"condition_id": "0xdef", "outcomePrices": [0.72, 0.28]}
    ]
    with patch("kalshi_trader.data.polymarket_client.requests.get", return_value=mock_resp):
        result = client.get_probabilities(["0xdef"])
    assert result == {"0xdef": 0.72}


def test_get_probabilities_skips_on_network_error():
    """Network failures are swallowed; that condition ID is absent from result."""
    client = PolymarketClient()
    with patch("kalshi_trader.data.polymarket_client.requests.get", side_effect=Exception("timeout")):
        result = client.get_probabilities(["0xbad"])
    assert result == {}


def test_get_probabilities_multiple_ids():
    """Multiple condition IDs are each fetched and returned."""
    client = PolymarketClient()

    def mock_get(url, params, timeout):
        m = MagicMock()
        m.raise_for_status.return_value = None
        cid = params["condition_id"]
        if cid == "0x111":
            m.json.return_value = [{"condition_id": "0x111", "outcomePrices": '["0.60", "0.40"]'}]
        else:
            m.json.return_value = [{"condition_id": "0x222", "outcomePrices": '["0.30", "0.70"]'}]
        return m

    with patch("kalshi_trader.data.polymarket_client.requests.get", side_effect=mock_get):
        result = client.get_probabilities(["0x111", "0x222"])
    assert result["0x111"] == pytest.approx(0.60)
    assert result["0x222"] == pytest.approx(0.30)


import pytest
```

**Step 2: Run to verify they fail**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_polymarket.py -v
```
Expected: FAIL — module not found

**Step 3: Implement `PolymarketClient`**

Create `kalshi_trader/data/polymarket_client.py`:

```python
import json
import requests
from typing import Dict, List


class PolymarketClient:
    GAMMA_API = "https://gamma-api.polymarket.com"

    def get_probabilities(self, condition_ids: List[str]) -> Dict[str, float]:
        """
        Fetch YES probabilities for given Polymarket condition IDs.
        Returns {condition_id: probability} for successful fetches only.
        Failures are silently skipped.
        """
        results = {}
        for cid in condition_ids:
            try:
                resp = requests.get(
                    f"{self.GAMMA_API}/markets",
                    params={"condition_id": cid},
                    timeout=10,
                )
                resp.raise_for_status()
                markets = resp.json()
                if not isinstance(markets, list):
                    markets = [markets]
                for market in markets:
                    prices_raw = market.get("outcomePrices")
                    if prices_raw is None:
                        continue
                    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                    if prices:
                        results[cid] = float(prices[0])
                        break
            except Exception:
                continue
        return results
```

**Step 4: Run all polymarket tests**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_polymarket.py -v
```
Expected: All 4 PASS

**Step 5: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/data/polymarket_client.py tests/test_polymarket.py && git commit -m "feat: add PolymarketClient for fetching YES probabilities from Gamma API"
```

---

### Task 6: Integrate Polymarket into `ExternalSignalCollector`

Load the ticker mapping file, fetch Polymarket prices for all mapped tickers, and populate `ExternalSignals.correlated_prices` in `collect()`. If the mapping file is absent or empty, this is a silent no-op.

**Files:**
- Modify: `kalshi_trader/data/external_signals.py`
- Test: `tests/test_external_signals.py`

**Step 1: Write the failing test**

Add to `tests/test_external_signals.py`:

```python
def test_collector_populates_correlated_prices_from_mapping(tmp_path):
    """When ticker_mappings_file is set, correlated_prices is populated from Polymarket."""
    import json
    from unittest.mock import patch
    from kalshi_trader.data.polymarket_client import PolymarketClient

    mapping = {"KXTEST-1": "0xabc123"}
    mapping_file = tmp_path / "mappings.json"
    mapping_file.write_text(json.dumps(mapping))

    cfg = KalshiConfig(data_dir=str(tmp_path), ticker_mappings_file=str(mapping_file))
    collector = ExternalSignalCollector(cfg)

    with patch.object(collector, "_fetch_economic_releases", return_value=[]):
        with patch.object(collector, "_fetch_news", return_value=[]):
            with patch.object(collector, "_fetch_polls", return_value=[]):
                with patch.object(PolymarketClient, "get_probabilities", return_value={"0xabc123": 0.72}):
                    signals = collector.collect()

    assert signals.correlated_prices == {"KXTEST-1": 0.72}


def test_collector_skips_correlated_prices_when_no_mapping(tmp_path):
    """When ticker_mappings_file is empty string, correlated_prices is empty."""
    cfg = KalshiConfig(data_dir=str(tmp_path), ticker_mappings_file="")
    collector = ExternalSignalCollector(cfg)
    with patch.object(collector, "_fetch_economic_releases", return_value=[]):
        with patch.object(collector, "_fetch_news", return_value=[]):
            with patch.object(collector, "_fetch_polls", return_value=[]):
                signals = collector.collect()
    assert signals.correlated_prices == {}
```

**Step 2: Run to verify they fail**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_external_signals.py::test_collector_populates_correlated_prices_from_mapping tests/test_external_signals.py::test_collector_skips_correlated_prices_when_no_mapping -v
```
Expected: FAIL

**Step 3: Update `external_signals.py`**

Add the following to `ExternalSignalCollector`:

At the top of the file, add the import:
```python
import json
from kalshi_trader.data.polymarket_client import PolymarketClient
```

In `__init__`, after the existing setup, load the mapping file:
```python
self._ticker_mappings: dict = {}
if cfg.ticker_mappings_file:
    try:
        with open(cfg.ticker_mappings_file) as f:
            self._ticker_mappings = json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
```

Add the fetch method:
```python
def _fetch_polymarket_prices(self) -> dict:
    """Fetch YES probabilities for all mapped Kalshi tickers from Polymarket."""
    if not self._ticker_mappings:
        return {}
    condition_ids = list(self._ticker_mappings.values())
    # condition_id -> probability
    raw = PolymarketClient().get_probabilities(condition_ids)
    # Invert: kalshi_ticker -> probability
    return {
        kalshi_ticker: raw[condition_id]
        for kalshi_ticker, condition_id in self._ticker_mappings.items()
        if condition_id in raw
    }
```

In `collect()`, after the existing try/except blocks, add:
```python
correlated = {}
try:
    correlated = self._fetch_polymarket_prices()
except Exception as e:
    self.logger.warning(f"Polymarket prices fetch failed: {e}")

signals = ExternalSignals(
    timestamp=ts,
    economic_releases=releases,
    news_headlines=news,
    poll_data=polls,
    correlated_prices=correlated,
)
```

(Replace the existing `ExternalSignals(...)` construction — currently it doesn't pass `correlated_prices`.)

**Step 4: Run all external signals tests**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_external_signals.py -v
```
Expected: All PASS

**Step 5: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/data/external_signals.py tests/test_external_signals.py && git commit -m "feat: populate ExternalSignals.correlated_prices from Polymarket via ticker mapping file"
```

---

### Task 7: Wire exit handling + Polymarket feed into `run_live.py`

Three changes to `run_live.py`:
1. Update `record_open_position` call to pass new fields (`entry_price`, `entry_ts`, `direction`, `strategy_name`)
2. Add exit-checking loop before new signal processing
3. Update `_update_correlated_prices` to read from `ext_signals.correlated_prices`

**Files:**
- Modify: `kalshi_trader/scripts/run_live.py`

No new test needed — script logic. Verify with import check and full test suite.

**Step 1: Update `record_open_position` call**

In `trading_loop`, find the block (around line 92-96):
```python
if result.get("status") not in ("rejected",):
    cost = signal.size * (entry_price / 100.0)
    risk_manager.record_open_position(
        signal.ticker, cost, category=snap.category
    )
```

Replace with:
```python
if result.get("status") not in ("rejected",):
    cost = signal.size * (entry_price / 100.0)
    risk_manager.record_open_position(
        signal.ticker,
        cost,
        category=snap.category,
        entry_price=entry_price,
        entry_ts=int(time.time()),
        direction=signal.direction,
        strategy_name=signal.strategy_name,
    )
```

**Step 2: Add exit-checking loop**

In `trading_loop`, after `_update_correlated_prices(arb_strategy, ext_signals)` and before the `for snap in snapshots:` loop, add:

```python
# Check open positions for settlement or early exit
strategy_map = {s.name: s for s in strategies}
for ticker in list(risk_manager._open_positions.keys()):
    snap = next((s for s in snapshots if s.ticker == ticker), None)
    if snap is None:
        continue
    meta = risk_manager.get_position_meta(ticker)
    if meta is None:
        continue

    if snap.settled is not None:
        # Market settled — close regardless of strategy
        exit_price = 99 if snap.settled else 1
        if cfg.execution_mode == "paper":
            executor.close_position(ticker, exit_price)
        risk_manager.close_position(ticker)
        logger.info(
            f"Settled close: {ticker} ({'YES' if snap.settled else 'NO'}) @ {exit_price}c"
        )

    else:
        strategy = strategy_map.get(meta.strategy_name)
        if strategy and strategy.on_exit(
            meta.entry_price, meta.entry_ts, meta.direction, snap, ext_signals
        ):
            # Strategy requested early close
            if cfg.execution_mode == "paper":
                executor.close_position(ticker, int(snap.mid_price or meta.entry_price))
            else:
                executor.close_position(ticker)
            risk_manager.close_position(ticker)
            logger.info(f"Early exit: {ticker} via {meta.strategy_name}")
```

**Step 3: Update `_update_correlated_prices`**

Replace the current implementation:
```python
def _update_correlated_prices(arb_strategy: ArbitrageStrategy, ext_signals) -> None:
    """Feed Polymarket-sourced probabilities into ArbitrageStrategy."""
    for ticker, prob in ext_signals.correlated_prices.items():
        arb_strategy.set_correlated_price(ticker, prob)
```

**Step 4: Verify importable**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -c "from kalshi_trader.scripts.run_live import trading_loop, _update_correlated_prices; print('ok')"
```
Expected: `ok`

**Step 5: Run full test suite**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -q --tb=short
```
Expected: All tests PASS

**Step 6: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/scripts/run_live.py && git commit -m "feat: wire position exit loop and Polymarket correlated prices into trading loop"
```

---

## Final Verification

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -v --tb=short
```

All tests should pass. Then verify all entry points import cleanly:

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -c "
from kalshi_trader.scripts.run_live import main
from kalshi_trader.scripts.collect_data import main
from kalshi_trader.scripts.run_research import main
print('all imports ok')
"
```

---

## Summary

| Task | Files | Type |
|------|-------|------|
| 1 | `risk/risk_manager.py` | Feature |
| 2 | `strategies/base_strategy.py`, 3 strategy files | Feature |
| 3 | `config.py` | Config |
| 4 | `data/models.py` | Data model |
| 5 | `data/polymarket_client.py` (new) | Feature |
| 6 | `data/external_signals.py` | Integration |
| 7 | `scripts/run_live.py` | Wiring |
