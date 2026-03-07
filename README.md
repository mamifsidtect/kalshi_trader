# Kalshi Prediction Market Trader

A research-first prediction market trading system using the [Kalshi](https://kalshi.com) Python SDK. Supports market making, directional, and arbitrage strategies across all Kalshi market categories (economic, political, sports, weather).

## Architecture

Two separated layers:

**Research Layer** (offline, no live orders)
- Collect and store historical Kalshi market data and external signals
- Test signal predictive accuracy
- Backtest strategies against historical data with a promotion gate

**Live Layer** (activated after research validates a strategy)
- Paper trading (simulated fills) or live order execution
- Risk manager: position sizing, exposure limits, daily loss halt
- Web dashboard at `http://localhost:8000`

## Project Structure

```
kalshi_trader/
├── client/             # Kalshi SDK wrapper (auth, retries)
├── data/               # Market collector + external signals (FRED, news, Metaculus)
├── research/           # Backtester + signal tester
├── strategies/         # MarketMaker, Directional, Arbitrage
├── risk/               # Risk manager
├── execution/          # PaperTrader + LiveTrader
├── web/                # FastAPI dashboard
└── scripts/            # Entry points
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

### 3. Collect data (run for several days to build a dataset)

```bash
python -m kalshi_trader.scripts.collect_data
```

### 4. Research — test signals and backtest strategies

```bash
python -m kalshi_trader.scripts.run_research --strategy MarketMaker --days 7
```

### 5. Paper trade (validate live behavior safely)

```bash
python -m kalshi_trader.scripts.run_live
# Dashboard at http://localhost:8000
```

### 6. Go live (only after satisfactory paper trading results)

```bash
EXECUTION_MODE=live python -m kalshi_trader.scripts.run_live
```

## Strategies

| Strategy | Description |
|----------|-------------|
| `MarketMaker` | Quotes both YES/NO sides, captures bid-ask spread on liquid markets |
| `Directional` | Takes YES/NO based on external signal confidence (news, polls, price) |
| `Arbitrage` | Exploits mispricing between Kalshi markets and correlated external data |

## Progression Gates

```
Data Collection
      │
Signal Testing (accuracy > baseline?)
      │
Backtesting (Sharpe > 0.5, win rate > 52%)
      │
Paper Trading (positive P&L over N days)
      │
Live Trading
```

Promotion to live trading is **manual**: set `EXECUTION_MODE=live` in `.env` after reviewing paper results.

## Web Dashboard

| Page | URL | Description |
|------|-----|-------------|
| Dashboard | `/` | P&L, win rate, open positions, signal feed |
| Positions | `/positions` | Live/paper positions, auto-refresh |
| Signal Explorer | `/research/signals` | Historical signal accuracy |
| Backtester | `/research/backtest` | Run backtests interactively |
| Market Browser | `/research/markets` | Browse collected markets by category |

## Configuration

Key settings in `config.py` or via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `KALSHI_ENVIRONMENT` | `demo` | `demo` or `prod` |
| `EXECUTION_MODE` | `paper` | `paper` or `live` |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

Risk parameters (set in `config.py`):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_position_pct` | 5% | Max bankroll per position |
| `daily_loss_limit_pct` | 3% | Daily loss halt threshold |
| `max_total_exposure_pct` | 30% | Max total open exposure |

## Running Tests

```bash
pytest tests/ -v
```

## Disclaimer

**This software is for educational and research purposes only.** Trading prediction markets involves risk of financial loss. Always test in paper mode before trading with real money. The authors are not responsible for any financial losses.

## License

MIT
