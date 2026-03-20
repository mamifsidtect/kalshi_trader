# Promotion Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-save the best sweep config per strategy to disk and load it at paper-trading startup, replacing hardcoded strategy defaults.

**Architecture:** A new `promoter.py` module provides `save_promoted_config()` and `load_promoted_configs()`. The sweeper calls save after finding a best config. `run_live.py` calls load at startup and instantiates only strategies with promoted configs.

**Tech Stack:** Python stdlib (json, os, tempfile, datetime). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-03-20-promotion-bridge-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `kalshi_trader/research/promoter.py` | Create | Save/load promoted configs to/from `{data_dir}/promoted/` |
| `tests/test_promoter.py` | Create | Unit tests for promoter module |
| `kalshi_trader/research/parameter_sweeper.py` | Modify (line ~183) | Call `save_promoted_config()` after best found |
| `kalshi_trader/web/routes/research.py` | Modify (lines ~134-152) | Call `save_promoted_config()` in sweep endpoint |
| `kalshi_trader/scripts/run_live.py` | Modify (lines 9-20, 31, 37-61) | Load promoted configs, guard arb_strategy |

---

### Task 1: Promoter Module — `save_promoted_config`

**Files:**
- Create: `kalshi_trader/research/promoter.py`
- Test: `tests/test_promoter.py`

- [ ] **Step 1: Write failing test for save_promoted_config**

```python
# tests/test_promoter.py
import json
import os
import tempfile
from kalshi_trader.config import KalshiConfig
from kalshi_trader.research.backtester import BacktestResult


def _make_config(tmp_dir):
    cfg = KalshiConfig()
    cfg.data_dir = tmp_dir
    return cfg


def _make_backtest_result():
    return BacktestResult(
        strategy_name="MarketMaker",
        total_trades=23,
        win_rate=0.62,
        total_pnl=14.50,
        sharpe=0.85,
        max_drawdown=3.20,
        avg_hold_bars=3600.0,
    )


def test_save_promoted_config_writes_json():
    from kalshi_trader.research.promoter import save_promoted_config
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        params = {"min_spread": 3, "min_volume": 50}
        bt = _make_backtest_result()
        save_promoted_config(cfg, "MarketMaker", params, bt)

        path = os.path.join(tmp, "promoted", "MarketMaker.json")
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data["strategy_name"] == "MarketMaker"
        assert data["params"] == params
        assert data["backtest"]["sharpe"] == 0.85
        assert data["backtest"]["win_rate"] == 0.62
        assert data["backtest"]["total_pnl"] == 14.50
        assert data["backtest"]["total_trades"] == 23
        assert "promoted_at" in data
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py::test_save_promoted_config_writes_json -v`
Expected: FAIL — `ImportError: cannot import name 'save_promoted_config'`

- [ ] **Step 3: Implement save_promoted_config**

```python
# kalshi_trader/research/promoter.py
"""
Promotion bridge: persist and load the best sweep configs per strategy.

Promoted configs are saved to {config.data_dir}/promoted/<StrategyName>.json
by the parameter sweeper. run_live.py loads them at startup to instantiate
only strategies with backtest-validated parameters.
"""
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict

from kalshi_trader.config import KalshiConfig
from kalshi_trader.research.backtester import BacktestResult
from kalshi_trader.utils.logger import get_logger


def _promoted_dir(config: KalshiConfig) -> str:
    return os.path.join(config.data_dir, "promoted")


def save_promoted_config(
    config: KalshiConfig,
    strategy_name: str,
    params: Dict[str, Any],
    backtest_result: BacktestResult,
) -> str:
    """Save promoted config to disk. Returns the file path written."""
    log = get_logger(__name__, config.log_level)
    promoted_dir = _promoted_dir(config)
    os.makedirs(promoted_dir, exist_ok=True)

    data = {
        "strategy_name": strategy_name,
        "params": params,
        "backtest": {
            "sharpe": backtest_result.sharpe,
            "win_rate": backtest_result.win_rate,
            "total_pnl": backtest_result.total_pnl,
            "total_trades": backtest_result.total_trades,
        },
        "promoted_at": datetime.now(timezone.utc).isoformat(),
    }

    path = os.path.join(promoted_dir, f"{strategy_name}.json")
    fd, tmp_path = tempfile.mkstemp(dir=promoted_dir, suffix=".tmp")
    try:
        os.write(fd, json.dumps(data, indent=2).encode())
    finally:
        os.close(fd)
    os.replace(tmp_path, path)

    log.info(f"Promoted {strategy_name} config to {path}")
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py::test_save_promoted_config_writes_json -v`
Expected: PASS

- [ ] **Step 5: Write test for overwrite behavior**

```python
# append to tests/test_promoter.py
def test_save_promoted_config_overwrites_existing():
    from kalshi_trader.research.promoter import save_promoted_config
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        bt = _make_backtest_result()
        save_promoted_config(cfg, "MarketMaker", {"min_spread": 3}, bt)
        save_promoted_config(cfg, "MarketMaker", {"min_spread": 7}, bt)

        path = os.path.join(tmp, "promoted", "MarketMaker.json")
        with open(path) as f:
            data = json.load(f)
        assert data["params"]["min_spread"] == 7
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py::test_save_promoted_config_overwrites_existing -v`
Expected: PASS (atomic write with os.replace handles this)

- [ ] **Step 7: Commit**

```bash
git add kalshi_trader/research/promoter.py tests/test_promoter.py
git commit -m "feat: add save_promoted_config to promoter module"
```

---

### Task 2: Promoter Module — `load_promoted_configs`

**Files:**
- Modify: `kalshi_trader/research/promoter.py`
- Modify: `tests/test_promoter.py`

- [ ] **Step 1: Write failing test for load_promoted_configs**

```python
# append to tests/test_promoter.py
def test_load_promoted_configs_reads_saved():
    from kalshi_trader.research.promoter import save_promoted_config, load_promoted_configs
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        bt = _make_backtest_result()
        save_promoted_config(cfg, "MarketMaker", {"min_spread": 3, "min_volume": 50}, bt)
        save_promoted_config(cfg, "Directional", {"confidence_threshold": 0.7}, bt)

        promoted = load_promoted_configs(cfg)
        assert "MarketMaker" in promoted
        assert "Directional" in promoted
        assert promoted["MarketMaker"] == {"min_spread": 3, "min_volume": 50}
        assert promoted["Directional"] == {"confidence_threshold": 0.7}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py::test_load_promoted_configs_reads_saved -v`
Expected: FAIL — `ImportError: cannot import name 'load_promoted_configs'`

- [ ] **Step 3: Implement load_promoted_configs**

Add to `kalshi_trader/research/promoter.py`:

```python
def load_promoted_configs(config: KalshiConfig) -> Dict[str, Dict[str, Any]]:
    """Load all promoted configs. Returns {strategy_name: params_dict}."""
    log = get_logger(__name__, config.log_level)
    promoted_dir = _promoted_dir(config)
    if not os.path.isdir(promoted_dir):
        return {}

    configs = {}
    now = datetime.now(timezone.utc)
    for filename in os.listdir(promoted_dir):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(promoted_dir, filename)
        try:
            with open(path) as f:
                data = json.load(f)
            name = data["strategy_name"]
            params = data["params"]

            # Log age for staleness awareness
            promoted_at = data.get("promoted_at", "")
            if promoted_at:
                try:
                    dt = datetime.fromisoformat(promoted_at)
                    age = now - dt
                    days = age.days
                    log.info(f"Loaded {name} config (promoted {days} day{'s' if days != 1 else ''} ago)")
                except (ValueError, TypeError):
                    log.info(f"Loaded {name} config (unknown age)")
            else:
                log.info(f"Loaded {name} config (unknown age)")

            configs[name] = params
        except (json.JSONDecodeError, KeyError, OSError) as e:
            log.warning(f"Skipping malformed promoted config {filename}: {e}")

    return configs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py::test_load_promoted_configs_reads_saved -v`
Expected: PASS

- [ ] **Step 5: Write test for missing directory**

```python
# append to tests/test_promoter.py
def test_load_promoted_configs_missing_dir():
    from kalshi_trader.research.promoter import load_promoted_configs
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        promoted = load_promoted_configs(cfg)
        assert promoted == {}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py::test_load_promoted_configs_missing_dir -v`
Expected: PASS

- [ ] **Step 7: Write test for malformed file handling**

```python
# append to tests/test_promoter.py
def test_load_promoted_configs_skips_malformed(caplog):
    from kalshi_trader.research.promoter import save_promoted_config, load_promoted_configs
    import logging
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        bt = _make_backtest_result()
        # Save one valid config
        save_promoted_config(cfg, "MarketMaker", {"min_spread": 3}, bt)
        # Write one malformed file
        bad_path = os.path.join(tmp, "promoted", "Bad.json")
        with open(bad_path, "w") as f:
            f.write("{not valid json")

        with caplog.at_level(logging.WARNING):
            promoted = load_promoted_configs(cfg)

        assert "MarketMaker" in promoted
        assert "Bad" not in promoted
        assert any("malformed" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py::test_load_promoted_configs_skips_malformed -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add kalshi_trader/research/promoter.py tests/test_promoter.py
git commit -m "feat: add load_promoted_configs to promoter module"
```

---

### Task 3: Sweeper Integration — Auto-Promote on Best Config

**Files:**
- Modify: `kalshi_trader/research/parameter_sweeper.py:183-185`
- Modify: `tests/test_promoter.py`

- [ ] **Step 1: Write failing integration test**

```python
# append to tests/test_promoter.py
def test_sweeper_auto_promotes_best_config():
    """ParameterSweeper.sweep() should auto-save promoted config when best exists."""
    from kalshi_trader.research.promoter import load_promoted_configs
    from kalshi_trader.research.parameter_sweeper import ParameterSweeper
    from kalshi_trader.data.models import MarketSnapshot, ExternalSignals
    import time

    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        # Use a tiny grid that will produce at least one promoted result
        # MarketMaker with low min_spread on high-spread data should trade and pass gate
        snaps = []
        for i in range(20):
            snaps.append(MarketSnapshot(
                ticker="T", timestamp=1700000000 + i * 60,
                yes_bid=40, yes_ask=50, no_bid=50, no_ask=60,
                volume=500, open_interest=200, category="financial",
                settled=True if i == 19 else None,
            ))
        signals_obj = ExternalSignals(timestamp=int(time.time()))
        sweeper = ParameterSweeper(cfg)
        report = sweeper.sweep(
            "MarketMaker", snaps, lambda ts: signals_obj,
            param_grid={"min_spread": [1], "min_volume": [0], "contracts_per_quote": [1],
                        "exit_profit_cents": [0], "exit_time_hours": [0]},
        )
        # If the sweep found a promotable config, it should be saved
        if report.best:
            promoted = load_promoted_configs(cfg)
            assert "MarketMaker" in promoted
```

- [ ] **Step 2: Run test to verify it fails (or passes vacuously)**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py::test_sweeper_auto_promotes_best_config -v`
Expected: If report.best exists, FAIL because promoted dir is empty (save not called yet)

- [ ] **Step 3: Add save_promoted_config call to parameter_sweeper.py**

In `kalshi_trader/research/parameter_sweeper.py`, add import at top (after line 22):

```python
from kalshi_trader.research.promoter import save_promoted_config
```

Then insert after line 183 (`report.best = report.all_results[0]`), before `self._log_summary`:

```python
        if report.best:
            save_promoted_config(self.config, strategy_name, report.best.params, report.best.backtest)
```

The full block around lines 182-186 becomes:

```python
        if report.all_results and report.all_results[0].promoted:
            report.best = report.all_results[0]

        if report.best:
            save_promoted_config(self.config, strategy_name, report.best.params, report.best.backtest)

        self._log_summary(report, rank_by)
        return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py::test_sweeper_auto_promotes_best_config -v`
Expected: PASS

- [ ] **Step 5: Run existing research tests to check for regressions**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_research.py -v`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add kalshi_trader/research/parameter_sweeper.py tests/test_promoter.py
git commit -m "feat: auto-promote best config in parameter sweeper"
```

---

### Task 4: Web Dashboard Integration — Auto-Promote in Sweep Endpoint

**Files:**
- Modify: `kalshi_trader/web/routes/research.py:105-156`

- [ ] **Step 1: Add save_promoted_config call and promoted field to sweep endpoint**

In `kalshi_trader/web/routes/research.py`, the sweep endpoint already calls `sweeper.sweep()` which now auto-promotes via the sweeper integration (Task 3). However, per the spec, the web endpoint should also add a `"promoted"` field to its response so the frontend knows.

Replace lines 134-153 (the `best = None` block through the return statement):

```python
        best = None
        promoted = False
        if report.best:
            best = {
                "params": report.best.params,
                "backtest": {
                    "total_trades": report.best.backtest.total_trades,
                    "win_rate": report.best.backtest.win_rate,
                    "total_pnl": report.best.backtest.total_pnl,
                    "sharpe": report.best.backtest.sharpe,
                    "max_drawdown": report.best.backtest.max_drawdown,
                },
            }
            promoted = True

        return {
            "strategy": req.strategy,
            "total_combinations": report.total_combinations,
            "promoted_count": len(report.promoted_results),
            "best": best,
            "top_results": top_results,
            "promoted": promoted,
        }
```

Note: The spec shows a direct `save_promoted_config()` call here, but since Task 3 added that call inside `sweeper.sweep()`, calling it again in the endpoint would be redundant (double-write). The sweeper handles promotion; the endpoint only adds the `promoted` response field. This is an intentional deviation from the spec for DRY.

- [ ] **Step 2: Run web tests to check for regressions**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_web.py -v`
Expected: All existing tests PASS

- [ ] **Step 3: Commit**

```bash
git add kalshi_trader/web/routes/research.py
git commit -m "feat: add promoted field to sweep endpoint response"
```

---

### Task 5: run_live.py — Load Promoted Configs at Startup

**Files:**
- Modify: `kalshi_trader/scripts/run_live.py:9-20,31,37-61`
- Modify: `tests/test_promoter.py`

- [ ] **Step 1: Write failing test for strategy loading from promoted configs**

```python
# append to tests/test_promoter.py
def test_load_and_instantiate_strategies():
    """Promoted configs should produce working strategy instances."""
    from kalshi_trader.research.promoter import save_promoted_config, load_promoted_configs
    from kalshi_trader.research.parameter_sweeper import STRATEGY_CLASSES
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        bt = _make_backtest_result()
        save_promoted_config(cfg, "MarketMaker", {"min_spread": 5, "min_volume": 100}, bt)
        save_promoted_config(cfg, "Directional", {"confidence_threshold": 0.7, "contracts": 1}, bt)

        promoted = load_promoted_configs(cfg)
        strategies = []
        for name, params in promoted.items():
            cls = STRATEGY_CLASSES.get(name)
            assert cls is not None, f"Unknown strategy: {name}"
            instance = cls(**params)
            strategies.append(instance)

        assert len(strategies) == 2
        names = {s.name for s in strategies}
        assert "MarketMaker" in names
        assert "Directional" in names
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py::test_load_and_instantiate_strategies -v`
Expected: PASS (promoter module + strategy classes already exist)

- [ ] **Step 3: Write test for TypeError handling on bad params**

```python
# append to tests/test_promoter.py
def test_load_skips_incompatible_params():
    """Strategy with unknown params should be skipped, not crash."""
    from kalshi_trader.research.promoter import save_promoted_config, load_promoted_configs
    from kalshi_trader.research.parameter_sweeper import STRATEGY_CLASSES
    from kalshi_trader.strategies.arbitrage import ArbitrageStrategy
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        bt = _make_backtest_result()
        # Save a config with an invalid param name
        save_promoted_config(cfg, "MarketMaker", {"nonexistent_param": 99}, bt)
        # Save a valid config too
        save_promoted_config(cfg, "Directional", {"confidence_threshold": 0.7}, bt)

        promoted = load_promoted_configs(cfg)
        strategies = []
        for name, params in promoted.items():
            cls = STRATEGY_CLASSES.get(name)
            if cls is None:
                continue
            try:
                instance = cls(**params)
            except TypeError:
                continue
            strategies.append(instance)

        # Only Directional should load; MarketMaker should be skipped
        assert len(strategies) == 1
        assert strategies[0].name == "Directional"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py::test_load_skips_incompatible_params -v`
Expected: PASS

- [ ] **Step 5: Write test for empty promoted configs path**

```python
# append to tests/test_promoter.py
def test_no_promoted_configs_returns_empty():
    """When no promoted configs exist, load returns empty and instantiation loop produces nothing."""
    from kalshi_trader.research.promoter import load_promoted_configs
    from kalshi_trader.research.parameter_sweeper import STRATEGY_CLASSES
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        promoted = load_promoted_configs(cfg)
        assert promoted == {}

        strategies = []
        for name, params in promoted.items():
            cls = STRATEGY_CLASSES.get(name)
            if cls:
                strategies.append(cls(**params))
        assert len(strategies) == 0
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py::test_no_promoted_configs_returns_empty -v`
Expected: PASS

- [ ] **Step 7: Modify run_live.py imports**

Replace lines 9-26 of `kalshi_trader/scripts/run_live.py`:

```python
import threading
import time
from datetime import datetime, timezone
from kalshi_trader.config import load_config
from kalshi_trader.client.kalshi_client import KalshiClient
from kalshi_trader.data.market_collector import MarketCollector
from kalshi_trader.data.external_signals import ExternalSignalCollector
from kalshi_trader.strategies.arbitrage import ArbitrageStrategy
from kalshi_trader.research.promoter import load_promoted_configs
from kalshi_trader.research.parameter_sweeper import STRATEGY_CLASSES
from kalshi_trader.risk.risk_manager import RiskManager
from kalshi_trader.execution.paper_trader import PaperTrader
from kalshi_trader.execution.live_trader import LiveTrader
from kalshi_trader.utils.logger import get_logger
from kalshi_trader.web.services.data_service import DataService
from collections import deque
```

- [ ] **Step 8: Modify _update_correlated_prices to accept Optional**

Replace lines 31-34:

```python
def _update_correlated_prices(arb_strategy, ext_signals) -> None:
    """Feed Polymarket-sourced probabilities into ArbitrageStrategy."""
    if arb_strategy is None:
        return
    for ticker, prob in ext_signals.correlated_prices.items():
        arb_strategy.set_correlated_price(ticker, prob)
```

- [ ] **Step 9: Modify trading_loop to load promoted configs**

Replace lines 37-47 (the function signature through strategy list):

```python
def trading_loop(cfg, client, risk_manager, executor, logger):
    market_collector = MarketCollector(client, cfg)
    signal_collector = ExternalSignalCollector(cfg)

    promoted = load_promoted_configs(cfg)
    strategies = []
    arb_strategy = None
    for name, params in promoted.items():
        cls = STRATEGY_CLASSES.get(name)
        if cls is None:
            logger.warning(f"Unknown strategy in promoted config: {name}")
            continue
        try:
            instance = cls(**params)
        except TypeError as e:
            logger.warning(f"Skipping {name}: promoted params incompatible with constructor: {e}")
            continue
        strategies.append(instance)
        if isinstance(instance, ArbitrageStrategy):
            arb_strategy = instance
        logger.info(f"Loaded promoted config for {name}: {params}")

    if not strategies:
        logger.warning("No promoted configs found. Run a parameter sweep first.")
        return
```

Line 61 (`_update_correlated_prices(arb_strategy, ext_signals)`) remains unchanged — the function now handles `None` safely from Step 8.

- [ ] **Step 10: Run all promoter tests**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/test_promoter.py -v`
Expected: All PASS

- [ ] **Step 11: Commit**

```bash
git add kalshi_trader/scripts/run_live.py tests/test_promoter.py
git commit -m "feat: run_live.py loads promoted configs instead of hardcoded defaults"
```

---

### Task 6: Final Verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run a quick import smoke test**

Run: `cd /home/mycool/claudetesting/kalshi_trader && python -c "from kalshi_trader.research.promoter import save_promoted_config, load_promoted_configs; print('OK')"`
Expected: Prints "OK"

- [ ] **Step 3: Commit if any fixes were needed, then verify clean state**

Run: `cd /home/mycool/claudetesting/kalshi_trader && git status`
Expected: Clean working tree
