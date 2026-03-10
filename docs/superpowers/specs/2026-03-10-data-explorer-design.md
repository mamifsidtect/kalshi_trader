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
| `kalshi_trader/web/routes/data_explorer.py` | FastAPI router — 2 page routes + 2 API routes |
| `kalshi_trader/web/services/data_explorer_service.py` | Reads `data/` directory, aggregates snapshot data |
| `kalshi_trader/web/templates/data_explorer.html` | Coverage overview page (card grid) |
| `kalshi_trader/web/templates/data_explorer_market.html` | Per-market detail page (5 charts) |

### Modified files

| File | Change |
|------|--------|
| `kalshi_trader/web/app.py` | Register `data_explorer` router; instantiate `DataExplorerService` into `app.state.data_explorer_service` |
| `kalshi_trader/config.py` | Change default `dashboard_port` from `8000` to `55055`; add `DASHBOARD_PORT` env var loading |
| `kalshi_trader/web/templates/base.html` | Add `<a href="/data-explorer">Data Explorer</a>` nav link alongside existing nav items |

### Routes

| Method | Path | Returns |
|--------|------|---------|
| GET | `/data-explorer` | HTML coverage overview page |
| GET | `/data-explorer/{ticker}` | HTML market detail page |
| GET | `/api/v1/data-explorer/markets` | JSON list of all markets with metadata |
| GET | `/api/v1/data-explorer/market/{ticker}` | JSON all snapshots for one ticker |

### Service registration

`DataExplorerService` is instantiated in `app.py` at startup and stored on `app.state.data_explorer_service`, following the same pattern as the existing `DataService` (`app.state.data_service`). Routes access it via `request.app.state.data_explorer_service`.

---

## Data Service

`DataExplorerService(config: KalshiConfig)` — two read-only methods. It does not share state with `DataService`; it reads directly from the `data/` directory on disk.

### `get_all_markets() -> List[Dict]`

Walks `data/{date}/{ticker}/` directories. For each ticker returns:

```python
{
    "ticker": str,
    "category": str,           # from snapshot, empty string if unknown
    "title": str,              # human-readable market title
    "snapshot_count": int,
    "days_covered": int,
    "date_range": str,         # e.g. "Mar 7–10" (abbreviated 3-char month, en-dash, no year)
                               # Multi-month example: "Feb 28–Mar 3"
    "settled": Optional[bool], # from most recent snapshot (True=YES won, False=NO won, None=open)
    "is_sparse": bool,         # True if snapshot_count < 100
    "sparkline": List[float],  # last ≤20 non-null mid_price values, ascending by timestamp
}
```

**Sparkline rules:** Take all snapshots sorted ascending by timestamp, filter out those with `mid_price is None`, take the last 20, return as a list of floats. If fewer than 20 non-null values exist, return however many there are. If zero, return `[]`.

**Categories** are derived dynamically from the data (not hardcoded). The filter tabs on the UI are built from the distinct category values present in the returned market list, plus "All".

**If `data/` directory is empty or missing:** return `[]`.

### `get_market_snapshots(ticker: str) -> List[Dict]`

Loads all JSON files for a ticker, sorted ascending by timestamp. Returns:

```python
[
    {
        "timestamp": int,           # Unix seconds
        "mid_price": Optional[float],  # (yes_bid + yes_ask) / 2, or None
        "spread": Optional[int],    # yes_ask - yes_bid, or None if either is None
        "volume": int,
        "open_interest": int,
        "settled": Optional[bool],
    },
    ...
]
```

**If ticker not found:** raise `HTTPException(status_code=404, detail="Ticker not found")`.
**If ticker folder exists but is empty:** return `[]` (200 OK, empty list).
**If a JSON file is malformed:** skip that file and continue (log a warning).

---

## Frontend

### Coverage Overview (`/data-explorer`)

- **Summary bar** at top: total markets, total snapshots, days collected
- **Category filter tabs:** "All" plus one tab per distinct category found in data. Active tab filters the card grid client-side (no page reload). JavaScript handles filtering.
- **Card grid** — 3 columns. Each card:
  - Ticker name (bold)
  - `{category} · {snapshot_count} snapshots · {days_covered} days`
  - Inline SVG sparkline (YES mid price trend, 80×20px viewBox). If sparkline data is empty, show a flat grey line.
  - Status badge:
    - `settled is None` → green "● Open"
    - `settled is True` → red "● Settled YES"
    - `settled is False` → grey "● Settled NO"
    - If `is_sparse=True`: orange card border + "⚠ Sparse data" instead of status badge
  - Clicking a card navigates to `/data-explorer/{ticker}`

### Market Detail (`/data-explorer/{ticker}`)

- **Header:** back link (← Data Explorer), ticker, title, category, snapshot count, date range, status badge (same logic as card)
- **Data load:** single `fetch("/api/v1/data-explorer/market/{ticker}")` on page load. While loading, show a spinner. On error (404 or network failure), show an inline error message.
- **Timestamp display:** Chart.js x-axis labels use JavaScript `new Date(timestamp * 1000).toLocaleString()` to convert Unix seconds to the user's local timezone. No server-side timezone conversion.
- **Five charts** rendered with Chart.js (loaded from CDN — same approach as any existing charts, or add CDN link to base.html if not present):

  1. **YES Mid Price** — line chart, blue (`#58a6ff`). X-axis: timestamps. Y-axis: 0–100 cents. If market is settled, draw a vertical annotation line at the last timestamp using Chart.js annotation plugin or a simple canvas overlay.
  2. **Bid/Ask Spread** — line chart, purple (`#d2a8ff`). Y-axis: cents (0+).
  3. **Volume / Open Interest** — grouped bar chart. Volume in blue (`#1f6feb`), open interest in grey (`#8b949e`).
  4. **Snapshots per Hour** — bar chart. Bucket timestamps by hour, count snapshots per bucket. Green (`#3fb950`) bars for buckets with ≥ 5 snapshots; orange (`#f0883e`) for < 5; missing buckets appear as gaps.

- If `snapshot_count = 0` (empty data), show a single "No data available for this market" message instead of charts.

---

## Port Change

`KalshiConfig.dashboard_port` default changes from `8000` → `55055`. Env var `DASHBOARD_PORT` overrides it. Update the README to reflect the new default port.

---

## Error Handling Summary

| Scenario | Behaviour |
|----------|-----------|
| `data/` directory missing | `get_all_markets()` returns `[]`; overview page shows "No data collected yet." |
| Ticker not found | 404 JSON response; detail page shows error message |
| Ticker folder empty | 200, empty snapshot list; detail page shows "No data available" |
| Malformed JSON snapshot | Skip file, log warning, continue |
| Network error on client fetch | Show inline error in the chart area |

---

## CORS

Not needed. The reverse proxy exposes port 55055 directly; all requests are same-origin from the browser's perspective.

---

## Non-Goals

- No write operations (read-only exploration)
- No real-time updates (static historical snapshots)
- No authentication
- No export/download functionality
- No pagination (load all snapshots for a ticker in one request — acceptable for a research tool)
