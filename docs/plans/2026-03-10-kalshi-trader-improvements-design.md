# Kalshi Trader Improvements Design
**Date:** 2026-03-10

## Overview

Full-pass improvement of the kalshi_trader codebase covering 9 real bugs, 3 disconnected features that need wiring, and 3 worthwhile additions. All changes are localized — no architectural redesign required.

---

## Section 1: Bug Fixes

### 1. `no_bid`/`no_ask` missing from `_market_to_dict`
**File:** `kalshi_trader/client/kalshi_client.py`

`_market_to_dict` never populates `no_bid` or `no_ask`, so every `MarketSnapshot` has `None` for those fields. This silently breaks `MarketMakerStrategy` direction logic and `ArbitrageStrategy`.

**Fix:** Derive them from YES prices — Kalshi is binary so `no_bid = 100 - yes_ask` and `no_ask = 100 - yes_bid`. Use API values if present, fall back to derivation.

---

### 2. Wrong entry price for "no" direction trades
**File:** `kalshi_trader/scripts/run_live.py`

`entry_price = snap.yes_ask or 50` always uses the YES ask regardless of signal direction. NO trades get priced incorrectly.

**Fix:** `entry_price = (snap.yes_ask if signal.direction == "yes" else snap.no_ask) or 50`

---

### 3. `live_trader.close_position` uses wrong side
**File:** `kalshi_trader/execution/live_trader.py`

When closing a position, the code re-uses `pos["side"]` and `action="buy"` — this opens a second position instead of closing. Also `price=99` is hardcoded.

**Fix:** Use `action="sell"` when closing, and derive a reasonable exit price from the current orderbook or pass it in as a parameter.

---

### 4. Risk manager exposure tracking never called
**File:** `kalshi_trader/scripts/run_live.py`

After `executor.execute()` succeeds, `risk_manager.record_open_position()` is never called. The `_open_positions` dict stays empty forever, so `max_total_exposure_pct` never fires.

**Fix:** Call `risk_manager.record_open_position(signal.ticker, cost, category=snap.category)` after each successful execution.

---

### 5. `risk_manager.reset_daily()` never called
**File:** `kalshi_trader/scripts/run_live.py`

Once the daily loss limit triggers and `_halted = True`, it never resets. Trading stays halted permanently across days.

**Fix:** At the top of each trading loop iteration, check if the UTC date has advanced since the last reset. If so, call `risk_manager.reset_daily()`. No external scheduler needed.

---

### 6. Backtester mixes snapshots across tickers
**File:** `kalshi_trader/research/backtester.py`

Snapshots from multiple tickers are passed in as a flat list. A position opened on `TICKER-A` can be closed when `TICKER-B`'s `settled` field appears — completely wrong backtest results for multi-ticker datasets.

**Fix:** Group snapshots by ticker first, run the simulation independently per ticker, then merge `trade_log` and `pnl_series` across tickers before computing aggregate stats.

---

### 7. `PaperTrader.execute` silently overwrites open positions
**File:** `kalshi_trader/execution/paper_trader.py`

`self._positions[signal.ticker] = order` overwrites any existing open position for the same ticker without closing it or logging a warning. This loses track of the original entry.

**Fix:** Check `if signal.ticker in self._positions` before executing. Log a warning and skip (or stack) rather than overwrite.

---

### 8. Non-atomic cache write in `external_signals.py`
**File:** `kalshi_trader/data/external_signals.py`

`_cache` uses a plain `open(path, "w")` write, which can leave a partial/corrupt file if interrupted. `market_collector.py` already uses the correct `tempfile.mkstemp` + `os.replace` atomic pattern.

**Fix:** Adopt the same atomic write pattern used in `market_collector.py`.

---

### 9. O(n) SIGNAL_FEED using `list.pop(0)`
**File:** `kalshi_trader/scripts/run_live.py`

`SIGNAL_FEED` is a plain list. Each `pop(0)` is O(n). With high-frequency updates this degrades.

**Fix:** Replace with `collections.deque(maxlen=200)`. Remove the manual length check and `pop(0)`.

---

## Section 2: Missing Wiring

### 10. Wire up `risk_manager.size_position()`
**File:** `kalshi_trader/scripts/run_live.py`

`RiskManager.size_position()` calculates the correct number of contracts based on bankroll and `max_position_pct`, but it's never called. All trades use whatever size the strategy defaults to (1 contract).

**Fix:** After `validate()` approves a signal, set `signal.size = risk_manager.size_position(entry_price)` before calling `executor.execute()`.

---

### 11. Enforce `max_category_exposure_pct`
**Files:** `kalshi_trader/risk/risk_manager.py`

`max_category_exposure_pct` exists in config but `RiskManager.validate()` never checks it.

**Fix:** Change `record_open_position` to accept an optional `category` parameter. Store `(exposure, category)` per ticker. In `validate()`, sum exposure for matching categories and compare against `bankroll * config.max_category_exposure_pct`.

---

### 12. Wire `ArbitrageStrategy` into `run_live.py`
**Files:** `kalshi_trader/scripts/run_live.py`, `kalshi_trader/strategies/arbitrage.py`

`ArbitrageStrategy` exists and is tested, but never runs in the live loop. It has no mechanism to receive external prices.

**Fix:** Add `ArbitrageStrategy` to the strategies list in `run_live.py`. Add a `_update_correlated_prices(arb_strategy, ext_signals)` helper that populates it from `poll_data` when matching tickers are found. Starts as a near-no-op but the wiring is live.

---

## Section 3: New Additions

### 13. Daily reset scheduling (in-loop)
**File:** `kalshi_trader/scripts/run_live.py`

Track the last-reset date in the trading loop. At the top of each iteration, if `datetime.now(timezone.utc).date() > last_reset_date`, call `risk_manager.reset_daily()` and update the stored date.

---

### 14. Orderbook-based live mid-price
**Files:** `kalshi_trader/web/services/data_service.py`, `kalshi_trader/scripts/run_live.py`

The existing `MarketSnapshot.mid_price` uses snapshot data which can be stale between collection intervals. `KalshiClient.get_orderbook()` exists but is never called.

**Addition:** Add `DataService.get_live_mid_price(client, ticker)` that calls `client.get_orderbook(ticker)` and computes mid from best bid/ask. Use this in `run_live.py` as the entry price when available, falling back to `snap.yes_ask or 50`.

---

### 15. `no_bid`/`no_ask` derivation fallback (covered in fix #1)
The derivation pattern (`no_bid = api_value or (100 - yes_ask)`) in `_market_to_dict` serves double duty as both a bug fix and a robust addition — it handles APIs that return these fields directly as well as APIs that don't.

---

## Files Changed

| File | Changes |
|------|---------|
| `kalshi_trader/client/kalshi_client.py` | Add `no_bid`/`no_ask` derivation to `_market_to_dict` |
| `kalshi_trader/scripts/run_live.py` | Entry price fix, risk wiring, daily reset, deque, arb strategy, size_position |
| `kalshi_trader/execution/live_trader.py` | Fix close_position side and price |
| `kalshi_trader/execution/paper_trader.py` | Guard against overwriting open positions |
| `kalshi_trader/data/external_signals.py` | Atomic cache write |
| `kalshi_trader/research/backtester.py` | Group by ticker before simulating |
| `kalshi_trader/risk/risk_manager.py` | Add category to record_open_position, enforce category exposure |
| `kalshi_trader/web/services/data_service.py` | Add `get_live_mid_price()` |

## Out of Scope

- Redesigning the strategy interface
- Adding new strategies beyond wiring ArbitrageStrategy
- UI/template changes
- Database storage (flat-file JSON remains)
