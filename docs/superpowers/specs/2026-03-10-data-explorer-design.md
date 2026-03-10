# Data Explorer — Design Spec

**Date:** 2026-03-10
**Goal:** Add a data exploration UI to the existing kalshi_trader web dashboard so collected market snapshots can be browsed and visualized before backtesting.

---

## Overview

Two new pages added to the existing FastAPI dashboard. The app moves from port 8000 to port 55055 to fit the user's reverse proxy setup. No new server process — everything runs inside the existing `run_live.py`-launched uvicorn instance.

---

## Architecture

### New files

| File | Purpose |
|------|---------|
| `kalshi_trader/web/routers/data_explorer.py` | FastAPI router — 2 page routes + 2 API routes |
| `kalshi_trader/web/services/data_explorer_service.py` | Reads `data/` directory, aggregates snapshot data |
| `kalshi_trader/web/templates/data_explorer.html` | Coverage overview page (card grid) |
| `kalshi_trader/web/templates/data_explorer_market.html` | Per-market detail page (5 charts) |

### Modified files

| File | Change |
|------|--------|
| `kalshi_trader/web/app.py` | Register `data_explorer` router |
| `kalshi_trader/config.py` | Change default `web_port` from 8000 to 55055 (or add `web_port` field if absent) |
| `kalshi_trader/web/templates/base.html` | Add "Data Explorer" nav link |

### Routes

| Method | Path | Returns |
|--------|------|---------|
| GET | `/data-explorer` | HTML coverage overview page |
| GET | `/data-explorer/{ticker}` | HTML market detail page |
| GET | `/api/v1/data-explorer/markets` | JSON list of all markets with metadata |
| GET | `/api/v1/data-explorer/market/{ticker}` | JSON all snapshots for one ticker |

---

## Data Service

`DataExplorerService` — two read-only methods:

### `get_all_markets() -> List[Dict]`

Walks `data/{date}/{ticker}/` directories. For each ticker returns:
- `ticker` (str)
- `category` (str)
- `title` (str)
- `snapshot_count` (int)
- `days_covered` (int)
- `date_range` (str) — e.g. `"Mar 7–10"`
- `settled` (Optional[bool]) — from most recent snapshot
- `is_sparse` (bool) — True if snapshot_count < 100 (threshold TBD)
- `sparkline` (List[float]) — last 20 mid_price values for the card sparkline

### `get_market_snapshots(ticker: str) -> List[Dict]`

Loads all JSON files for a ticker, sorted by timestamp. Each dict:
- `timestamp` (int)
- `mid_price` (Optional[float])
- `spread` (Optional[int]) — `yes_ask - yes_bid`
- `volume` (int)
- `open_interest` (int)
- `settled` (Optional[bool])

---

## Frontend

### Coverage Overview (`/data-explorer`)

- Summary bar at top: total markets, total snapshots, days collected
- Category filter tabs: All / financial / economic / sports / weather
- Card grid — 3 columns, each card shows:
  - Ticker name
  - Category · snapshot count · days
  - Inline SVG sparkline (YES mid price trend)
  - Settlement badge (Open / Settled YES / Settled NO) or ⚠ Sparse data warning (orange border) if `is_sparse`
  - Clicking a card navigates to `/data-explorer/{ticker}`

### Market Detail (`/data-explorer/{ticker}`)

- Header: back link, ticker, title, category, snapshot count, date range, settlement badge
- Five charts rendered with Chart.js (loaded from CDN):
  1. **YES Mid Price** — line chart over time (blue). Settlement date marked with vertical dashed line if resolved.
  2. **Bid/Ask Spread** — line chart over time (purple)
  3. **Volume / Open Interest** — grouped bar chart (blue bars)
  4. **Snapshots per Hour** — bar chart (green); gaps shown as missing bars or orange bars below threshold
- Charts share the same x-axis (timestamps)
- All data loaded in a single `fetch()` call to `/api/v1/data-explorer/market/{ticker}` on page load

---

## Port Change

`KalshiConfig.web_port` default changes from `8000` → `55055`. Environment variable `WEB_PORT` overrides it. The README is updated to reflect the new default.

---

## Non-Goals

- No write operations (this is read-only exploration)
- No real-time updates (data is static historical snapshots)
- No authentication
- No export/download functionality
