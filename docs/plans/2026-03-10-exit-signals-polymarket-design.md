# Exit Signals + Polymarket Price Feed Design
**Date:** 2026-03-10

## Overview

Two features:
1. **Strategy exit signals** — strategies decide when to close positions via `on_exit()`, triggered by price targets, time limits, or market settlement
2. **Polymarket price feed** — feed real external probabilities into `ArbitrageStrategy` by fetching prices from the Polymarket Gamma API using a user-maintained ticker mapping file

---

## Feature 1: Strategy Exit Signals

### `BaseStrategy.on_exit`

Add `exit_profit_cents: int = 0` and `exit_time_hours: int = 0` to each strategy's `__init__` (`MarketMakerStrategy`, `DirectionalStrategy`, `ArbitrageStrategy`).

Add to `BaseStrategy`:

```python
def on_exit(self, entry_price: int, entry_ts: int, market: MarketSnapshot, signals: ExternalSignals) -> bool:
    """Return True to close this position early. Default checks profit target and time limit."""
    import time
    if self.exit_profit_cents > 0 and market.mid_price is not None:
        profit = market.mid_price - entry_price  # for YES positions
        if profit >= self.exit_profit_cents:
            return True
    if self.exit_time_hours > 0:
        elapsed_hours = (time.time() - entry_ts) / 3600
        if elapsed_hours >= self.exit_time_hours:
            return True
    return False
```

Subclasses only override for custom logic. Setting a param to `0` disables that check.

### `RiskManager` position metadata

Add a `PositionMeta` dataclass:

```python
@dataclass
class PositionMeta:
    exposure: float
    category: str
    entry_ts: int
    strategy_name: str
```

Replace `Dict[str, Tuple[float, str]]` with `Dict[str, PositionMeta]` in `_open_positions`. Update `record_open_position(ticker, exposure, category, entry_ts, strategy_name)`. Add:

```python
def has_position(self, ticker: str) -> bool:
    return ticker in self._open_positions

def get_position_meta(self, ticker: str) -> Optional[PositionMeta]:
    return self._open_positions.get(ticker)
```

Update `validate()` total/category exposure sums to use `meta.exposure` and `meta.category`.

### Trading loop exit handling

After collecting snapshots, before processing new signals, check all open positions:

```python
strategy_map = {s.name: s for s in strategies}
for ticker in list(risk_manager._open_positions.keys()):
    snap = next((s for s in snapshots if s.ticker == ticker), None)
    if snap is None:
        continue
    meta = risk_manager.get_position_meta(ticker)

    if snap.settled is not None:
        # Settlement close — always fires, no strategy involved
        exit_price = 99 if snap.settled else 1
        if cfg.execution_mode == "paper":
            executor.close_position(ticker, exit_price)
        risk_manager.close_position(ticker)

    else:
        strategy = strategy_map.get(meta.strategy_name)
        if strategy and strategy.on_exit(meta.entry_price, meta.entry_ts, snap, ext_signals):
            # Early exit — strategy requested close
            if cfg.execution_mode == "paper":
                executor.close_position(ticker, snap.mid_price or 50)
            else:
                executor.close_position(ticker)  # places sell order
            risk_manager.close_position(ticker)
```

`PositionMeta` needs `entry_price` too — add it to the dataclass and `record_open_position`.

### Config additions

```python
exit_profit_cents: int = 0   # 0 = disabled
exit_time_hours: int = 0     # 0 = disabled
```

Load from env vars `EXIT_PROFIT_CENTS` and `EXIT_TIME_HOURS`.

---

## Feature 2: Polymarket Price Feed

### `PolymarketClient`

New file: `kalshi_trader/data/polymarket_client.py`

```python
class PolymarketClient:
    GAMMA_API = "https://gamma-api.polymarket.com"

    def get_probabilities(self, condition_ids: List[str]) -> Dict[str, float]:
        """
        Fetch YES probabilities for given Polymarket condition IDs.
        Returns {condition_id: probability} for successful fetches.
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
                data = resp.json()
                markets = data if isinstance(data, list) else [data]
                for market in markets:
                    prices_raw = market.get("outcomePrices")
                    if prices_raw:
                        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                        if prices:
                            results[cid] = float(prices[0])
                            break
            except Exception:
                continue
        return results
```

### Ticker mapping file

User-maintained JSON at path set by `KalshiConfig.ticker_mappings_file`:

```json
{
  "KXELECPREZ-24-R": "0xabc123...",
  "KXFED-24-50BPS": "0xdef456..."
}
```

Kalshi ticker → Polymarket condition ID. If the file is not configured or doesn't exist, the feature is silently disabled.

### `ExternalSignals.correlated_prices`

Add to the `ExternalSignals` dataclass:

```python
correlated_prices: Dict[str, float] = field(default_factory=dict)
```

### `ExternalSignalCollector` changes

- Load `ticker_mappings_file` in `__init__` (cache the parsed dict)
- Add `_fetch_polymarket_prices() -> Dict[str, float]` using `PolymarketClient`
- In `collect()`, populate `signals.correlated_prices` from the fetch result

### `_update_correlated_prices` in `run_live.py`

Replace the current poll-data loop:

```python
def _update_correlated_prices(arb_strategy: ArbitrageStrategy, ext_signals) -> None:
    for ticker, prob in ext_signals.correlated_prices.items():
        arb_strategy.set_correlated_price(ticker, prob)
```

### Config additions

```python
ticker_mappings_file: str = ""   # path to JSON mapping file
```

Load from env var `TICKER_MAPPINGS_FILE`.

---

## Files Changed

| File | Change |
|------|--------|
| `kalshi_trader/strategies/base_strategy.py` | Add `exit_profit_cents`, `exit_time_hours`, `on_exit()` |
| `kalshi_trader/strategies/market_maker.py` | Add exit params to `__init__` |
| `kalshi_trader/strategies/directional.py` | Add exit params to `__init__` |
| `kalshi_trader/strategies/arbitrage.py` | Add exit params to `__init__` |
| `kalshi_trader/risk/risk_manager.py` | Add `PositionMeta`, update `record_open_position`, add `has_position`, `get_position_meta` |
| `kalshi_trader/config.py` | Add `exit_profit_cents`, `exit_time_hours`, `ticker_mappings_file` |
| `kalshi_trader/data/models.py` | Add `correlated_prices` to `ExternalSignals` |
| `kalshi_trader/data/polymarket_client.py` | New file |
| `kalshi_trader/data/external_signals.py` | Load mappings, add `_fetch_polymarket_prices`, populate `correlated_prices` |
| `kalshi_trader/scripts/run_live.py` | Exit handling loop, update `_update_correlated_prices`, update `record_open_position` call |

## Out of Scope

- Auto-discovery of Polymarket↔Kalshi ticker mappings
- Webhook-based settlement notification (poll-based is sufficient)
- Per-position exit param overrides (strategy-level config is enough)
