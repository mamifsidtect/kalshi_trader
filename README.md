# Kalshi Prediction Market Trader

A research-first prediction market trading system using the [Kalshi](https://kalshi.com) Python SDK. Supports market making, directional, arbitrage, single-condition arbitrage, and Bregman divergence strategies across all Kalshi market categories (economic, political, sports, weather). Includes automatic parameter sweeps, Kelly criterion position sizing, and VWAP-based slippage modeling.

## Architecture

Two separated layers:

**Research Layer** (offline, no live orders)
- Collect and store historical Kalshi market data and external signals
- Backfill settlement outcomes for already-collected snapshots
- Test signal predictive accuracy
- Backtest strategies against historical data with a promotion gate
- Automatic parameter sweeps when default configs fail promotion
- VWAP-based slippage modeling for realistic backtest results

**Live Layer** (activated after research validates a strategy)
- Paper trading (simulated fills) or live order execution
- Risk manager: position sizing, exposure limits, daily loss halt
- Web dashboard at `http://localhost:55055`

## Project Structure

```
kalshi_trader/
├── client/             # Kalshi SDK wrapper (auth, retries)
├── data/               # Market collector, external signals (FRED, news, Polymarket)
│   └── models.py       # MarketSnapshot, ExternalSignals, Signal dataclasses
├── research/           # Backtester, signal tester, parameter sweeper
├── strategies/         # MarketMaker, Directional, Arbitrage, SingleConditionArb, BregmanDivergence, KellySizer
├── risk/               # Risk manager
├── execution/          # PaperTrader + LiveTrader
├── web/                # FastAPI dashboard + data explorer
│   └── services/       # DataService, DataExplorerService
├── scripts/            # Entry points (collect_data, run_research, run_live, run_dashboard)
└── utils/              # Logger
```

## Quick Start

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r kalshi_trader/requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your Kalshi API credentials
```

Required credentials:
- `KALSHI_API_KEY_ID` — your Kalshi API key ID
- `KALSHI_API_KEY_FILE` — path to the file containing your API private key

### 3. Collect data (run for several days to build a dataset)

```bash
python -m kalshi_trader.scripts.collect_data
```

Snapshots are saved to `data/<date>/<ticker>/<timestamp>.json` (one JSON file per market per collection interval).

### 4. Backfill settlement data

After markets have settled, backfill the outcomes into your stored snapshots so the backtester can use real settlement results:

```bash
python -m kalshi_trader.scripts.run_research --strategy MarketMaker --days 7 --backfill
```

The `--backfill` flag fetches settled markets from the Kalshi API and updates your stored snapshot files with `"settled": true` (YES won) or `"settled": false` (NO won). This only needs API credentials and only writes to your local data directory.

### 5. Research — test signals and backtest strategies

```bash
# Backtest MarketMaker over 7 days of collected data
python -m kalshi_trader.scripts.run_research --strategy MarketMaker --days 7

# Backtest Directional strategy
python -m kalshi_trader.scripts.run_research --strategy Directional --days 14

# Backtest new formulaic strategies
python -m kalshi_trader.scripts.run_research --strategy SingleConditionArb --days 14
python -m kalshi_trader.scripts.run_research --strategy BregmanDivergence --days 14

# Auto-sweep parameters when default config fails the promotion gate
python -m kalshi_trader.scripts.run_research --strategy Directional --sweep --days 14

# Sweep all strategies at once, rank by win rate
python -m kalshi_trader.scripts.run_research --sweep-all --rank-by win_rate --days 14

# Use VWAP-based slippage for more realistic backtests
python -m kalshi_trader.scripts.run_research --strategy SingleConditionArb --vwap-slippage --days 14
```

The backtester closes positions via three mechanisms (in priority order):
1. **Settlement** — market settles YES (`settled=True`) or NO (`settled=False`)
2. **Close time** — market's `close_time` passes, position exits at last mid-price
3. **Strategy exit** — `on_exit()` fires based on profit target or time limit

The backtester provides verbose progress output:
- Per-date data loading breakdown (tickers, snapshots, settlement coverage)
- Per-ticker processing progress (`[1/15] Processing TICKER-ABC (42 snapshots)`)
- Trade open/close events with reasons (settled, close_time, strategy exit) and hold durations
- Summary stats: total signals evaluated vs skipped, trades generated, cumulative P&L

Output includes trade count, win rate, total P&L, Sharpe ratio, max drawdown, and sample trades.

### 6. Paper trade (validate live behavior safely)

```bash
python -m kalshi_trader.scripts.run_live
# Dashboard at http://localhost:55055
```

### 7. Go live (only after satisfactory paper trading results)

```bash
EXECUTION_MODE=live python -m kalshi_trader.scripts.run_live
```

## Strategies

| Strategy | Description |
|----------|-------------|
| `MarketMaker` | Quotes both YES/NO sides, captures bid-ask spread. Uses `effective_no_bid` to handle markets that only report YES prices. |
| `Directional` | Takes YES/NO based on signal confidence (news, polls, price conviction). Fires when price is far from 50c. |
| `Arbitrage` | Exploits mispricing between Kalshi markets and correlated Polymarket data |
| `SingleConditionArb` | Buys the cheaper side when `yes_ask + no_ask < 100` (guaranteed profit on settlement). Based on research showing 41% of prediction market conditions exhibit this mispricing. |
| `BregmanDivergence` | Uses KL-divergence to measure information-theoretic distance between market-implied probability and fair-value estimates from external signals. Trades toward the Bregman projection when divergence exceeds a threshold. |

### Strategy Parameters

**MarketMaker:**
- `min_spread` — minimum bid-ask spread (in cents) to trigger a signal (default: 5)
- `min_volume` — minimum market volume to consider (default: 100; set to 0 for backtesting)

**Directional:**
- `confidence_threshold` — minimum score to generate a signal (default: 0.6)
- Scoring: price conviction (up to 0.65) + news (0.15) + polls (0.20) - economic releases (0.10)

**SingleConditionArb:**
- `min_edge_cents` — minimum profit edge in cents to trade (default: 5). From the research: edges below 5c get eaten by execution risk.
- `max_entry_price` — maximum entry price in cents (default: 95). Avoids taking positions near certainty.

**BregmanDivergence:**
- `min_divergence` — minimum KL-divergence threshold to trade (default: 0.05)
- Fair value is estimated from a weighted blend: correlated external prices (50%), poll data (25%), news sentiment (15%), market prior (10%)

### Kelly Criterion Position Sizing

A modified Kelly criterion is available for dynamic position sizing (`strategies/kelly_sizer.py`):

```
f* = (b*p - q) / b * sqrt(p)
```

Where `b` = edge/cost ratio, `p` = execution probability (adjusted for order book volume), `q` = 1-p. The `sqrt(p)` factor is a conservative half-Kelly variant that accounts for non-atomic fill risk on CLOBs. Sizing is also capped at 25% of order book depth to avoid moving the market.

## Automatic Parameter Sweeps

When a strategy's default parameters fail the promotion gate (Sharpe < 0.5 or win rate < 52%), the parameter sweeper can automatically search for a promotable configuration:

```bash
# Auto-sweep on failure
python -m kalshi_trader.scripts.run_research --strategy Directional --sweep

# Sweep all strategies
python -m kalshi_trader.scripts.run_research --sweep-all --rank-by sharpe
```

The sweeper tests all combinations from predefined parameter grids:

| Strategy | Parameters Swept |
|----------|-----------------|
| `MarketMaker` | min_spread (1-10), min_volume (0-200), exit_profit (0-8c), exit_time (0-12h) |
| `Directional` | confidence_threshold (0.3-0.8), exit_profit (0-8c), exit_time (0-12h) |
| `Arbitrage` | min_edge (0.02-0.15), exit_profit (0-8c), exit_time (0-12h) |
| `SingleConditionArb` | min_edge_cents (2-15), max_entry_price (85-95), exit_profit (0-8c), exit_time (0-12h) |
| `BregmanDivergence` | min_divergence (0.01-0.20), exit_profit (0-8c), exit_time (0-12h) |

Results are sorted by the chosen metric (sharpe or win_rate). The best promotable config is highlighted; if none pass the gate, the top 5 closest configs are shown.

The sweeper provides detailed progress output every 25 combinations including percentage complete, promoted count so far, best Sharpe found, and estimated time remaining. Parameter sweeps are also available in the web dashboard via the Backtester page.

## Progression Gates

```
Data Collection
      |
Signal Testing (accuracy > baseline?)
      |
Backtesting (Sharpe > 0.5, win rate > 52%)
      |  \--- fails? ---> Automatic Parameter Sweep
      |                         |
      |  <--- best config ------/
      |
Paper Trading (positive P&L over N days)
      |
Live Trading
```

Promotion to live trading is **manual**: set `EXECUTION_MODE=live` in `.env` after reviewing paper results. The parameter sweep step is automatic when using `--sweep`.

## Web Dashboard

The dashboard can be run standalone or as part of the live trading loop:

```bash
# Standalone — browse data, run backtests, explore signals without trading
python -m kalshi_trader.scripts.run_dashboard
python -m kalshi_trader.scripts.run_dashboard --port 8080

# Or as part of live trading (starts automatically)
python -m kalshi_trader.scripts.run_live
```

Runs on port 55055 by default (configurable via `DASHBOARD_PORT` env var or `--port`).

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | P&L, win rate, open positions, strategy overview, signal feed |
| Positions | `/positions` | Live/paper positions, auto-refresh |
| Data Explorer | `/data-explorer` | Browse collected markets, view snapshots and sparklines |
| Signal Explorer | `/research/signals` | Historical signal accuracy |
| Backtester | `/research/backtest` | Run backtests and parameter sweeps interactively |
| Market Browser | `/research/markets` | Browse collected markets by category |

The Backtester page supports all 4 strategies with per-strategy parameter controls, displays results with equity curves, a full trade log table (entry/exit/P&L/hold time/close reason), and includes a Parameter Sweep button that runs an exhaustive grid search and displays the top configurations.

## Configuration

Key settings via environment variables (or `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `KALSHI_API_KEY_ID` | | API key ID for authentication |
| `KALSHI_API_KEY_FILE` | | Path to API private key file |
| `KALSHI_ENVIRONMENT` | `demo` | `demo` or `prod` |
| `EXECUTION_MODE` | `paper` | `paper` or `live` |
| `DASHBOARD_PORT` | `55055` | Web dashboard port |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `DATA_DIR` | `data` | Directory for collected market data |

### Risk Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_position_pct` | 5% | Max bankroll per position |
| `daily_loss_limit_pct` | 3% | Daily loss halt threshold |
| `max_total_exposure_pct` | 30% | Max total open exposure |
| `max_category_exposure_pct` | 30% | Max exposure per category |

### Exit Conditions

Positions can be closed automatically based on two optional conditions:

| Variable | Default | Description |
|----------|---------|-------------|
| `EXIT_PROFIT_CENTS` | `0` (disabled) | Close position when profit reaches N cents |
| `EXIT_TIME_HOURS` | `0` (disabled) | Close position after N hours regardless of P&L |

Setting either to `0` disables that check. Both can be active at once — whichever triggers first closes the position.

```bash
EXIT_PROFIT_CENTS=15 EXIT_TIME_HOURS=24 python -m kalshi_trader.scripts.run_live
```

Markets that settle automatically trigger a close at 99c (YES win) or 1c (NO win).

### Polymarket Price Feed (ArbitrageStrategy)

`ArbitrageStrategy` can use live Polymarket probabilities as its external price source. Create a JSON mapping file linking Kalshi tickers to Polymarket condition IDs:

```json
{
  "KXBTC-25DEC-T50000": "0xabc123...",
  "KXECON-UNEMP-JAN": "0xdef456..."
}
```

Then set the path via env var:

```bash
TICKER_MAPPINGS_FILE=/path/to/mappings.json python -m kalshi_trader.scripts.run_live
```

Condition IDs can be found in the Polymarket URL or via the Gamma API. Tickers with no mapping are simply skipped.

## Running Tests

```bash
pytest tests/ -v
```

126 tests covering the full pipeline: config, data collection, strategies (including SingleConditionArb, BregmanDivergence, Kelly sizer), backtester (including VWAP slippage), parameter sweeper, risk manager, execution, web dashboard, and data explorer.

## Disclaimer

**This software is for educational and research purposes only.** Trading prediction markets involves risk of financial loss. Always test in paper mode before trading with real money. The authors are not responsible for any financial losses.

## License

MIT
