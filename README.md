# Kalshi Prediction Market Trader

A research-first prediction market trading system using the [Kalshi](https://kalshi.com) Python SDK. Supports market making, directional, and arbitrage strategies across all Kalshi market categories (economic, political, sports, weather).

## Architecture

Two separated layers:

**Research Layer** (offline, no live orders)
- Collect and store historical Kalshi market data and external signals
- Backfill settlement outcomes for already-collected snapshots
- Test signal predictive accuracy
- Backtest strategies against historical data with a promotion gate

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
├── research/           # Backtester + signal tester
├── strategies/         # MarketMaker, Directional, Arbitrage
├── risk/               # Risk manager
├── execution/          # PaperTrader + LiveTrader
├── web/                # FastAPI dashboard + data explorer
│   └── services/       # DataService, DataExplorerService
├── scripts/            # Entry points (collect_data, run_research, run_live)
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
```

The backtester closes positions via three mechanisms (in priority order):
1. **Settlement** — market settles YES (`settled=True`) or NO (`settled=False`)
2. **Close time** — market's `close_time` passes, position exits at last mid-price
3. **Strategy exit** — `on_exit()` fires based on profit target or time limit

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

### Strategy Parameters

**MarketMaker:**
- `min_spread` — minimum bid-ask spread (in cents) to trigger a signal (default: 5)
- `min_volume` — minimum market volume to consider (default: 100; set to 0 for backtesting)

**Directional:**
- `confidence_threshold` — minimum score to generate a signal (default: 0.6)
- Scoring: price conviction (up to 0.65) + news (0.15) + polls (0.20) - economic releases (0.10)

## Progression Gates

```
Data Collection
      |
Signal Testing (accuracy > baseline?)
      |
Backtesting (Sharpe > 0.5, win rate > 52%)
      |
Paper Trading (positive P&L over N days)
      |
Live Trading
```

Promotion to live trading is **manual**: set `EXECUTION_MODE=live` in `.env` after reviewing paper results.

## Web Dashboard

The dashboard runs on port 55055 by default (configurable via `DASHBOARD_PORT` env var).

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | P&L, win rate, open positions, signal feed |
| Positions | `/positions` | Live/paper positions, auto-refresh |
| Data Explorer | `/data-explorer` | Browse collected markets, view snapshots and sparklines |
| Signal Explorer | `/research/signals` | Historical signal accuracy |
| Backtester | `/research/backtest` | Run backtests interactively |
| Market Browser | `/research/markets` | Browse collected markets by category |

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

101 tests covering the full pipeline: config, data collection, strategies, backtester, risk manager, execution, web dashboard, and data explorer.

## Disclaimer

**This software is for educational and research purposes only.** Trading prediction markets involves risk of financial loss. Always test in paper mode before trading with real money. The authors are not responsible for any financial losses.

## License

MIT
