# Promotion Bridge: Auto-Promote Best Sweep Config to Paper Trading

## Problem

The research pipeline (backtester + parameter sweeper) identifies promotable strategy configs, but there's no automated path from discovery to paper trading. `run_live.py` hardcodes default strategy params, requiring manual edits to use promoted configs.

## Solution

A promoter module that bridges research and execution. Sweeps auto-save the best config per strategy to `{config.data_dir}/promoted/<StrategyName>.json`. `run_live.py` loads from these files instead of using hardcoded defaults. Strategies without a promoted config are skipped entirely.

## Design Decisions

- **Only the single best config per strategy is promoted** — no ranked lists, no history.
- **Multiple strategies run simultaneously** — each strategy has its own independent promoted config file.
- **No promoted config = strategy skipped** — no fallback to hardcoded defaults. No trading without backtest evidence.
- **Both CLI sweeps and web dashboard sweeps auto-promote** — same code path via the promoter module.
- **Separate files per strategy** — `{data_dir}/promoted/MarketMaker.json`, `{data_dir}/promoted/Directional.json`, etc. Cleaner per-strategy lifecycle than a single combined file.
- **No auto-demotion** — if a re-sweep finds no config passing the gate, the existing promoted config is left untouched. The loader logs the age of each promoted config at startup to surface staleness.
- **Sweep-all is CLI-only** — the web dashboard sweeps one strategy at a time via `run_sweep`. `--sweep-all` is only available via `run_research.py`.
- **Concurrent sweeps: last writer wins** — atomic writes prevent corruption, but if two sweeps for the same strategy run simultaneously, the last to finish overwrites the other. This is acceptable for this use case.

## Components

### 1. Promoter Module — `kalshi_trader/research/promoter.py`

New file with two public functions:

**`save_promoted_config(config, strategy_name, params, backtest_result)`**
- `config`: `KalshiConfig` — used to derive `config.data_dir`
- `strategy_name`: `str` — e.g., `"MarketMaker"`
- `params`: `Dict[str, Any]` — strategy constructor kwargs
- `backtest_result`: `BacktestResult` — extracts sharpe, win_rate, total_pnl, total_trades
- Promoted dir: `os.path.join(config.data_dir, "promoted")`
- Writes `{promoted_dir}/{strategy_name}.json`
- Creates promoted directory if it doesn't exist
- Uses atomic write (tempfile + `os.replace`) for crash safety
- Logs the promotion path
- File format:

```json
{
  "strategy_name": "MarketMaker",
  "params": {"min_spread": 3, "min_volume": 50, "exit_profit_cents": 5, "exit_time_hours": 6},
  "backtest": {"sharpe": 0.85, "win_rate": 0.62, "total_pnl": 14.50, "total_trades": 23},
  "promoted_at": "2026-03-20T14:30:00Z"
}
```

**`load_promoted_configs(config)`**
- Reads all `.json` files from `os.path.join(config.data_dir, "promoted")`
- Extracts the `"params"` sub-field from each file (not the entire file contents)
- Returns `Dict[str, Dict[str, Any]]` mapping strategy name to params dict
- Logs the age of each promoted config (e.g., "Loaded MarketMaker config (promoted 3 days ago)")
- Skips malformed files with a warning log
- Returns empty dict if directory doesn't exist

### 2. Sweeper Integration — `kalshi_trader/research/parameter_sweeper.py`

At the end of `ParameterSweeper.sweep()`, after `report.best` is identified:

```python
if report.best:
    save_promoted_config(self.config, strategy_name, report.best.params, report.best.backtest)
```

This covers both `sweep()` and `sweep_all()` (which calls `sweep()` per strategy). No changes to sweep logic, sorting, or ranking.

### 3. Web Dashboard Integration — `kalshi_trader/web/routes/research.py`

Since `sweeper.sweep()` now calls `save_promoted_config()` internally (Section 2), the web endpoint does not need a separate save call. It only adds a `"promoted"` boolean to the response payload so the frontend knows a config was auto-saved:

```python
promoted = True if report.best else False
```

Add `"promoted": promoted` to the return dict.

No changes to the backtest endpoint — only sweeps auto-promote.

### 4. Live Trading Loader — `kalshi_trader/scripts/run_live.py`

Replace hardcoded strategy instantiation (lines 40-47) with:

```python
from kalshi_trader.research.promoter import load_promoted_configs
from kalshi_trader.research.parameter_sweeper import STRATEGY_CLASSES
from kalshi_trader.strategies.arbitrage import ArbitrageStrategy

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

The existing `_update_correlated_prices(arb_strategy, ext_signals)` call in the trading loop is guarded with `if arb_strategy:` — it continues to work because `arb_strategy` is set during loading if an ArbitrageStrategy config was promoted.

Key behaviors:
- No promoted configs at all: logs warning and exits
- Some strategies promoted, others not: only promoted ones run
- `TypeError` on instantiation (e.g., param name mismatch): skips that strategy with a warning, doesn't crash
- ArbitrageStrategy gets special handling for `_update_correlated_prices` — detected via `isinstance` during loading

### 5. CLI Research Script — `kalshi_trader/scripts/run_research.py`

No direct changes needed. Promotion happens inside `ParameterSweeper.sweep()`, so `--sweep` and `--sweep-all` auto-promote. The existing `">>> BEST PROMOTABLE CONFIG <<<"` log still prints; `save_promoted_config()` adds its own log line confirming the file path.

## Data Flow

```
Parameter Sweep (CLI or Web)
  |
  v
ParameterSweeper.sweep()
  |-- ranks configs, identifies report.best
  |-- calls save_promoted_config()
  v
data/promoted/<StrategyName>.json
  |
  v
run_live.py startup
  |-- calls load_promoted_configs()
  |-- instantiates strategy classes with promoted params
  |-- skips strategies without promoted configs
  v
Paper Trading Loop (PaperTrader)
```

## Testing

- **Unit test `promoter.py`**: `save_promoted_config` writes valid JSON; `load_promoted_configs` reads it back correctly; handles missing directory; handles malformed files gracefully (skips with warning).
- **Integration test**: `ParameterSweeper.sweep()` auto-creates promoted file when best config exists; does not create one when no config passes gate.
- **`run_live.py` loading test**: Strategy instantiation from promoted configs produces working strategy instances with correct params.

## Files Changed

| File | Change |
|------|--------|
| `kalshi_trader/research/promoter.py` | **New** — save/load promoted configs |
| `kalshi_trader/research/parameter_sweeper.py` | Add `save_promoted_config()` call after best found |
| `kalshi_trader/web/routes/research.py` | Add `save_promoted_config()` call in sweep endpoint |
| `kalshi_trader/scripts/run_live.py` | Replace hardcoded strategies with promoted config loader |
| `tests/test_promoter.py` | **New** — unit tests for promoter module |
