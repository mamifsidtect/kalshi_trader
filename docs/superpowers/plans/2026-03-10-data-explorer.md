# Data Explorer Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only data exploration UI to the existing kalshi_trader FastAPI dashboard — a card-grid coverage overview and per-market detail page with 5 charts — and move the dashboard from port 8000 to 55055.

**Architecture:** Extend the existing FastAPI app with a new `data_explorer` route file and `DataExplorerService`. Two new HTML pages rendered via Jinja2 templates using Chart.js (already loaded in base.html). All data is read from the on-disk `data/{date}/{ticker}/` JSON files.

**Tech Stack:** Python 3.13, FastAPI, Jinja2, Chart.js 4 (CDN), pytest

**Run all tests with:** `cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -v`

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `kalshi_trader/config.py` | Change `dashboard_port` default to 55055, add `DASHBOARD_PORT` env var |
| Create | `kalshi_trader/web/services/data_explorer_service.py` | Reads data dir, aggregates snapshot metadata and chart data |
| Create | `tests/test_data_explorer_service.py` | Unit tests for DataExplorerService |
| Create | `kalshi_trader/web/routes/data_explorer.py` | 2 page routes + 2 API routes |
| Create | `tests/test_data_explorer_routes.py` | Integration tests for the API endpoints |
| Modify | `kalshi_trader/web/app.py` | Register router, instantiate DataExplorerService into app.state |
| Modify | `kalshi_trader/web/templates/base.html` | Add "Data Explorer" nav link |
| Create | `kalshi_trader/web/templates/data_explorer.html` | Coverage overview — card grid with sparklines and category tabs |
| Create | `kalshi_trader/web/templates/data_explorer_market.html` | Market detail — 5 Chart.js charts |

---

## Chunk 1: Foundation — Port Change and Data Service

### Task 1: Change default dashboard port to 55055

**Files:**
- Modify: `kalshi_trader/config.py`

No test needed — verified by import check and full suite.

- [ ] **Step 1: Read `kalshi_trader/config.py`**

- [ ] **Step 2: Change `dashboard_port` default and add env var loading**

In the `KalshiConfig` dataclass, change:
```python
dashboard_port: int = 8000
```
to:
```python
dashboard_port: int = 55055
```

In `load_config()`, after the existing env var blocks, add:
```python
if os.getenv("DASHBOARD_PORT"):
    cfg.dashboard_port = int(os.getenv("DASHBOARD_PORT"))
```

- [ ] **Step 3: Verify importable**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -c "from kalshi_trader.config import load_config; cfg = load_config(); print(cfg.dashboard_port)"
```
Expected: `55055`

- [ ] **Step 4: Run full test suite**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -q --tb=no
```
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/config.py && git commit -m "feat: change default dashboard_port to 55055, add DASHBOARD_PORT env var"
```

---

### Task 2: Create `DataExplorerService`

`DataExplorerService` is the data layer. It reads directly from the `data/` directory — it does NOT share state with `DataService`.

**Files:**
- Create: `kalshi_trader/web/services/data_explorer_service.py`
- Create: `tests/test_data_explorer_service.py`

**Data directory structure** (already on disk):
```
data/
└── {YYYY-MM-DD}/
    └── {ticker}/
        └── {timestamp_ns}.json    ← one MarketSnapshot per file
```

Each JSON file matches `MarketSnapshot.to_dict()`:
```json
{
  "ticker": "KXTEST-1",
  "timestamp": 1741564800,
  "yes_bid": 40, "yes_ask": 45,
  "no_bid": 55, "no_ask": 60,
  "volume": 100, "open_interest": 50,
  "category": "financial",
  "title": "Test Market",
  "close_time": "2026-03-15T00:00:00Z",
  "settled": null
}
```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_data_explorer_service.py`:

```python
import json
import os
import pytest
from kalshi_trader.config import KalshiConfig
from kalshi_trader.web.services.data_explorer_service import DataExplorerService


def _write_snapshot(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _snap(ticker="KXTEST-1", ts=1741564800, yes_bid=40, yes_ask=45,
          volume=100, oi=50, category="financial", title="Test Market",
          settled=None):
    return {
        "ticker": ticker,
        "timestamp": ts,
        "yes_bid": yes_bid, "yes_ask": yes_ask,
        "no_bid": 55, "no_ask": 60,
        "volume": volume, "open_interest": oi,
        "category": category, "title": title,
        "close_time": "2026-03-15T00:00:00Z",
        "settled": settled,
    }


def test_get_all_markets_empty_when_no_data(tmp_path):
    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    assert svc.get_all_markets() == []


def test_get_all_markets_aggregates_by_ticker(tmp_path):
    # Write 3 snapshots for one ticker across 2 dates
    for i, (date, ts) in enumerate([
        ("2026-03-08", 1741392000 + i * 60),
        ("2026-03-08", 1741392060 + i * 60),
        ("2026-03-09", 1741478400 + i * 60),
    ]):
        path = str(tmp_path / date / "KXTEST-1" / f"{ts}000000000.json")
        _write_snapshot(path, _snap(ts=ts))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    markets = svc.get_all_markets()

    assert len(markets) == 1
    m = markets[0]
    assert m["ticker"] == "KXTEST-1"
    assert m["snapshot_count"] == 3
    assert m["days_covered"] == 2
    assert m["category"] == "financial"


def test_get_all_markets_sparse_flag(tmp_path):
    # Only 50 snapshots — below threshold of 100
    date = "2026-03-08"
    for i in range(50):
        ts = 1741392000 + i * 60
        path = str(tmp_path / date / "KXTEST-1" / f"{ts}000000000.json")
        _write_snapshot(path, _snap(ts=ts))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    markets = svc.get_all_markets()
    assert markets[0]["is_sparse"] is True


def test_get_all_markets_not_sparse_at_100(tmp_path):
    date = "2026-03-08"
    for i in range(100):
        ts = 1741392000 + i * 60
        path = str(tmp_path / date / "KXTEST-1" / f"{ts}000000000.json")
        _write_snapshot(path, _snap(ts=ts))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    markets = svc.get_all_markets()
    assert markets[0]["is_sparse"] is False


def test_get_all_markets_sparkline_excludes_nulls(tmp_path):
    date = "2026-03-08"
    snaps = [
        _snap(ts=1741392000, yes_bid=None, yes_ask=None),  # mid_price = None
        _snap(ts=1741392060, yes_bid=40, yes_ask=45),       # mid_price = 42.5
        _snap(ts=1741392120, yes_bid=42, yes_ask=47),       # mid_price = 44.5
    ]
    for s in snaps:
        path = str(tmp_path / date / "KXTEST-1" / f"{s['timestamp']}000000000.json")
        _write_snapshot(path, s)

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    markets = svc.get_all_markets()
    sparkline = markets[0]["sparkline"]
    assert None not in sparkline
    assert len(sparkline) == 2
    assert sparkline[0] == pytest.approx(42.5)


def test_get_all_markets_sparkline_max_20(tmp_path):
    date = "2026-03-08"
    for i in range(25):
        ts = 1741392000 + i * 60
        path = str(tmp_path / date / "KXTEST-1" / f"{ts}000000000.json")
        _write_snapshot(path, _snap(ts=ts, yes_bid=40 + i, yes_ask=45 + i))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    markets = svc.get_all_markets()
    assert len(markets[0]["sparkline"]) == 20


def test_get_market_snapshots_returns_sorted(tmp_path):
    date = "2026-03-08"
    timestamps = [1741392120, 1741392000, 1741392060]  # out of order
    for ts in timestamps:
        path = str(tmp_path / date / "KXTEST-1" / f"{ts}000000000.json")
        _write_snapshot(path, _snap(ts=ts))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    snaps = svc.get_market_snapshots("KXTEST-1")

    assert len(snaps) == 3
    assert snaps[0]["timestamp"] < snaps[1]["timestamp"] < snaps[2]["timestamp"]


def test_get_market_snapshots_computes_spread(tmp_path):
    date = "2026-03-08"
    path = str(tmp_path / date / "KXTEST-1" / "1741392000000000000.json")
    _write_snapshot(path, _snap(ts=1741392000, yes_bid=40, yes_ask=48))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    snaps = svc.get_market_snapshots("KXTEST-1")
    assert snaps[0]["spread"] == 8  # int: yes_ask - yes_bid = 48 - 40
    assert isinstance(snaps[0]["spread"], int)


def test_get_all_markets_sparkline_empty_when_all_nulls(tmp_path):
    """Sparkline is [] when all snapshots have null mid_price."""
    date = "2026-03-08"
    for i in range(3):
        ts = 1741392000 + i * 60
        path = str(tmp_path / date / "KXTEST-1" / f"{ts}000000000.json")
        _write_snapshot(path, _snap(ts=ts, yes_bid=None, yes_ask=None))

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    markets = svc.get_all_markets()
    assert markets[0]["sparkline"] == []


def test_get_market_snapshots_404_unknown_ticker(tmp_path):
    from fastapi import HTTPException
    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    with pytest.raises(HTTPException) as exc:
        svc.get_market_snapshots("NONEXISTENT")
    assert exc.value.status_code == 404


def test_get_market_snapshots_empty_folder_returns_empty(tmp_path):
    # Create the ticker directory but no snapshot files
    ticker_dir = tmp_path / "2026-03-08" / "KXTEST-1"
    ticker_dir.mkdir(parents=True)

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    snaps = svc.get_market_snapshots("KXTEST-1")
    assert snaps == []


def test_get_market_snapshots_skips_malformed_json(tmp_path):
    date = "2026-03-08"
    good_path = str(tmp_path / date / "KXTEST-1" / "1741392000000000000.json")
    bad_path = str(tmp_path / date / "KXTEST-1" / "1741392060000000000.json")
    _write_snapshot(good_path, _snap(ts=1741392000))
    os.makedirs(os.path.dirname(bad_path), exist_ok=True)
    with open(bad_path, "w") as f:
        f.write("{{not valid json")

    cfg = KalshiConfig(data_dir=str(tmp_path))
    svc = DataExplorerService(cfg)
    snaps = svc.get_market_snapshots("KXTEST-1")
    assert len(snaps) == 1  # bad file skipped, good file returned
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_data_explorer_service.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError` — service not created yet.

- [ ] **Step 3: Implement `DataExplorerService`**

Create `kalshi_trader/web/services/data_explorer_service.py`:

```python
import json
import logging
import os
from typing import Dict, List, Optional

from fastapi import HTTPException

from kalshi_trader.config import KalshiConfig

_log = logging.getLogger(__name__)


class DataExplorerService:
    SPARSE_THRESHOLD = 100  # snapshots below this = is_sparse=True
    SPARKLINE_MAX = 20

    def __init__(self, config: KalshiConfig):
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all_markets(self) -> List[Dict]:
        """Return a summary dict per distinct ticker found in the data directory."""
        data_dir = self.config.data_dir
        if not os.path.isdir(data_dir):
            return []

        # Collect all snapshot paths grouped by ticker
        ticker_files: Dict[str, List[str]] = {}
        ticker_dates: Dict[str, set] = {}

        for date_entry in sorted(os.scandir(data_dir), key=lambda e: e.name):
            if not date_entry.is_dir():
                continue
            for ticker_entry in os.scandir(date_entry.path):
                if not ticker_entry.is_dir():
                    continue
                ticker = ticker_entry.name
                ticker_files.setdefault(ticker, [])
                ticker_dates.setdefault(ticker, set())
                ticker_dates[ticker].add(date_entry.name)
                for snap_file in os.scandir(ticker_entry.path):
                    if snap_file.name.endswith(".json"):
                        ticker_files[ticker].append(snap_file.path)

        if not ticker_files:
            return []

        results = []
        for ticker, file_paths in ticker_files.items():
            summary = self._build_market_summary(ticker, file_paths, ticker_dates[ticker])
            if summary:
                results.append(summary)

        return results

    def get_market_snapshots(self, ticker: str) -> List[Dict]:
        """
        Return all snapshots for a ticker, sorted ascending by timestamp.
        Raises HTTPException 404 if the ticker is not found in the data directory.
        Skips malformed JSON files (logs a warning).
        """
        data_dir = self.config.data_dir
        file_paths = []
        found = False

        if os.path.isdir(data_dir):
            for date_entry in os.scandir(data_dir):
                if not date_entry.is_dir():
                    continue
                ticker_dir = os.path.join(date_entry.path, ticker)
                if os.path.isdir(ticker_dir):
                    found = True
                    for snap_file in os.scandir(ticker_dir):
                        if snap_file.name.endswith(".json"):
                            file_paths.append(snap_file.path)

        if not found:
            raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found")

        snapshots = []
        for path in file_paths:
            snap = self._load_snapshot(path)
            if snap is not None:
                snapshots.append(snap)

        snapshots.sort(key=lambda s: s["timestamp"])
        return snapshots

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_snapshot(self, path: str) -> Optional[Dict]:
        """Load a single snapshot JSON file. Returns None on parse error."""
        try:
            with open(path) as f:
                data = json.load(f)
            yes_bid = data.get("yes_bid")
            yes_ask = data.get("yes_ask")
            mid_price = (yes_bid + yes_ask) / 2.0 if yes_bid is not None and yes_ask is not None else None
            spread = int(yes_ask - yes_bid) if yes_bid is not None and yes_ask is not None else None
            return {
                "timestamp": data.get("timestamp", 0),
                "mid_price": mid_price,
                "spread": spread,
                "volume": data.get("volume", 0),
                "open_interest": data.get("open_interest", 0),
                "settled": data.get("settled"),
            }
        except (json.JSONDecodeError, OSError, TypeError) as e:
            _log.warning(f"Skipping malformed snapshot file {path}: {e}")
            return None

    def _build_market_summary(self, ticker: str, file_paths: List[str], dates: set) -> Optional[Dict]:
        """Build the summary dict for a single ticker from its file paths."""
        if not file_paths:
            return None

        # Load all snapshots to build sparkline and get latest metadata
        snapshots = []
        for path in sorted(file_paths):
            snap_raw = self._load_raw(path)
            if snap_raw is not None:
                snapshots.append(snap_raw)

        if not snapshots:
            return None

        snapshots.sort(key=lambda s: s.get("timestamp", 0))
        latest = snapshots[-1]

        # Build sparkline: last ≤20 non-null mid_price values
        mid_prices = []
        for s in snapshots:
            yb = s.get("yes_bid")
            ya = s.get("yes_ask")
            if yb is not None and ya is not None:
                mid_prices.append((yb + ya) / 2.0)
        sparkline = mid_prices[-self.SPARKLINE_MAX:]

        # Date range string
        sorted_dates = sorted(dates)
        date_range = self._format_date_range(sorted_dates[0], sorted_dates[-1])

        return {
            "ticker": ticker,
            "category": latest.get("category", ""),
            "title": latest.get("title", ticker),
            "snapshot_count": len(file_paths),
            "days_covered": len(dates),
            "date_range": date_range,
            "settled": latest.get("settled"),
            "is_sparse": len(file_paths) < self.SPARSE_THRESHOLD,
            "sparkline": sparkline,
        }

    def _load_raw(self, path: str) -> Optional[Dict]:
        """Load raw JSON without transformation. Returns None on error."""
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _format_date_range(start: str, end: str) -> str:
        """Format 'YYYY-MM-DD' dates as 'Mar 7–10' or 'Feb 28–Mar 3'."""
        from datetime import datetime
        MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
        sm = MONTHS[s.month - 1]
        em = MONTHS[e.month - 1]
        if s.month == e.month:
            return f"{sm} {s.day}–{e.day}"
        return f"{sm} {s.day}–{em} {e.day}"
```

- [ ] **Step 4: Run all data explorer service tests**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_data_explorer_service.py -v
```
Expected: All 10 tests PASS.

- [ ] **Step 5: Run full suite to check no regressions**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -q --tb=no
```

- [ ] **Step 6: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/web/services/data_explorer_service.py tests/test_data_explorer_service.py && git commit -m "feat: add DataExplorerService for market coverage and snapshot data"
```

---

## Chunk 2: Routes, App Wiring, and Nav

### Task 3: Create `data_explorer` route file

**Files:**
- Create: `kalshi_trader/web/routes/data_explorer.py`
- Create: `tests/test_data_explorer_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_data_explorer_routes.py`:

```python
import json
import os
import pytest
from fastapi.testclient import TestClient
from kalshi_trader.config import KalshiConfig
from kalshi_trader.web.app import create_app
from kalshi_trader.web.services.data_explorer_service import DataExplorerService


def _write_snapshot(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


@pytest.fixture
def client(tmp_path):
    cfg = KalshiConfig(data_dir=str(tmp_path))
    # Write one snapshot so there's data to return
    snap = {
        "ticker": "KXTEST-1", "timestamp": 1741392000,
        "yes_bid": 40, "yes_ask": 45, "no_bid": 55, "no_ask": 60,
        "volume": 100, "open_interest": 50, "category": "financial",
        "title": "Test Market", "close_time": "2026-03-15T00:00:00Z",
        "settled": None,
    }
    _write_snapshot(str(tmp_path / "2026-03-08" / "KXTEST-1" / "1741392000000000000.json"), snap)
    app = create_app(cfg)
    return TestClient(app)


def test_api_markets_returns_list(client):
    resp = client.get("/api/v1/data-explorer/markets")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["ticker"] == "KXTEST-1"


def test_api_market_snapshots_returns_list(client):
    resp = client.get("/api/v1/data-explorer/market/KXTEST-1")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["timestamp"] == 1741392000


def test_api_market_snapshots_404_for_unknown(client):
    resp = client.get("/api/v1/data-explorer/market/NONEXISTENT")
    assert resp.status_code == 404


def test_page_data_explorer_returns_html(client):
    resp = client.get("/data-explorer")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_page_data_explorer_market_returns_html(client):
    resp = client.get("/data-explorer/KXTEST-1")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_data_explorer_routes.py -v 2>&1 | head -20
```
Expected: FAIL — routes not registered yet.

- [ ] **Step 3: Create the route file**

Create `kalshi_trader/web/routes/data_explorer.py`:

```python
import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import List

router = APIRouter()
_templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_templates_dir)


@router.get("/data-explorer", response_class=HTMLResponse)
async def data_explorer(request: Request):
    markets = request.app.state.data_explorer_service.get_all_markets()
    categories = sorted({m["category"] for m in markets if m["category"]})
    return templates.TemplateResponse(
        request,
        "data_explorer.html",
        {
            "markets": markets,
            "categories": categories,
            "total_snapshots": sum(m["snapshot_count"] for m in markets),
            "total_markets": len(markets),
            "days_collected": max((m["days_covered"] for m in markets), default=0),
        },
    )


@router.get("/data-explorer/{ticker}", response_class=HTMLResponse)
async def data_explorer_market(request: Request, ticker: str):
    return templates.TemplateResponse(
        request,
        "data_explorer_market.html",
        {"ticker": ticker},
    )


@router.get("/api/v1/data-explorer/markets")
async def api_data_explorer_markets(request: Request) -> List[dict]:
    return request.app.state.data_explorer_service.get_all_markets()


@router.get("/api/v1/data-explorer/market/{ticker}")
async def api_data_explorer_market(request: Request, ticker: str) -> List[dict]:
    return request.app.state.data_explorer_service.get_market_snapshots(ticker)
```

- [ ] **Step 4: Register router and service in `app.py`**

Read `kalshi_trader/web/app.py`, then make two changes:

Add import at top:
```python
from kalshi_trader.web.routes import data_explorer
from kalshi_trader.web.services.data_explorer_service import DataExplorerService
```

Inside `create_app()`, after the existing `app.state.data_service = ...` line, add:
```python
app.state.data_explorer_service = DataExplorerService(config)
```

After the existing `app.include_router(markets.router)` line, add:
```python
app.include_router(data_explorer.router)
```

- [ ] **Step 5: Create stub templates** (needed for route tests to pass)

Create minimal `kalshi_trader/web/templates/data_explorer.html`:
```html
{% extends "base.html" %}
{% block title %}Data Explorer{% endblock %}
{% block content %}<p>stub</p>{% endblock %}
```

Create minimal `kalshi_trader/web/templates/data_explorer_market.html`:
```html
{% extends "base.html" %}
{% block title %}{{ ticker }}{% endblock %}
{% block content %}<p>stub</p>{% endblock %}
```

- [ ] **Step 6: Run route tests**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_data_explorer_routes.py -v
```
Expected: All 5 PASS.

- [ ] **Step 7: Run full suite**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -q --tb=no
```

- [ ] **Step 8: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/web/routes/data_explorer.py kalshi_trader/web/app.py kalshi_trader/web/templates/data_explorer.html kalshi_trader/web/templates/data_explorer_market.html tests/test_data_explorer_routes.py && git commit -m "feat: add data explorer routes and wire DataExplorerService into app"
```

---

### Task 4: Add "Data Explorer" nav link to base.html

**Files:**
- Modify: `kalshi_trader/web/templates/base.html`

No separate test — covered by existing template rendering.

- [ ] **Step 1: Read `kalshi_trader/web/templates/base.html`**

- [ ] **Step 2: Add nav link**

Find the existing nav block:
```html
    <a href="/research/markets">Market Browser</a>
```

Add immediately after it:
```html
    <a href="/data-explorer">Data Explorer</a>
```

- [ ] **Step 3: Verify the page route still returns 200**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_data_explorer_routes.py::test_page_data_explorer_returns_html -v
```
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/web/templates/base.html && git commit -m "feat: add Data Explorer nav link to dashboard"
```

---

## Chunk 3: Templates

### Task 5: Build coverage overview template

Replace the stub `data_explorer.html` with the full card-grid page.

**Files:**
- Modify: `kalshi_trader/web/templates/data_explorer.html`

- [ ] **Step 1: Replace stub with full template**

Overwrite `kalshi_trader/web/templates/data_explorer.html`:

```html
{% extends "base.html" %}
{% block title %}Data Explorer{% endblock %}
{% block content %}
<div class="section-header">
  <h2>Data Explorer</h2>
  <span class="summary-bar">
    {{ total_markets }} markets &middot; {{ "{:,}".format(total_snapshots) }} snapshots &middot; {{ days_collected }} days collected
  </span>
</div>

<!-- Category filter tabs -->
<div class="category-tabs" id="categoryTabs">
  <button class="tab-btn active" data-cat="all" onclick="filterMarkets('all', this)">All</button>
  {% for cat in categories %}
  <button class="tab-btn" data-cat="{{ cat }}" onclick="filterMarkets('{{ cat }}', this)">{{ cat }}</button>
  {% endfor %}
</div>

{% if markets %}
<!-- Card grid -->
<div class="market-grid" id="marketGrid">
  {% for m in markets %}
  <a href="/data-explorer/{{ m.ticker }}" class="market-card{% if m.is_sparse %} market-card--sparse{% endif %}">
    <div class="market-card__ticker">{{ m.ticker }}</div>
    <div class="market-card__meta">{{ m.category }} &middot; {{ m.snapshot_count }} snapshots &middot; {{ m.days_covered }} days</div>

    <!-- Inline SVG sparkline -->
    <div class="market-card__sparkline">
      {% if m.sparkline %}
      {% set prices = m.sparkline %}
      {% set mn = prices | min %}
      {% set mx = prices | max %}
      {% set rng = (mx - mn) if (mx - mn) > 0 else 1 %}
      {% set w = 80 %}
      {% set h = 20 %}
      {% set n = prices | length %}
      <svg viewBox="0 0 {{ w }} {{ h }}" preserveAspectRatio="none" style="width:100%;height:20px;display:block;">
        <polyline
          points="{% for i in range(n) %}{{ (i / (n - 1 if n > 1 else 1)) * w | round(1) }},{{ (h - ((prices[i] - mn) / rng * h)) | round(1) }} {% endfor %}"
          fill="none"
          stroke="{% if m.is_sparse %}#f0883e{% else %}#58a6ff{% endif %}"
          stroke-width="1.5"
          {% if m.is_sparse %}stroke-dasharray="3,2"{% endif %}
        />
      </svg>
      {% else %}
      <svg viewBox="0 0 80 20" style="width:100%;height:20px;display:block;">
        <line x1="0" y1="10" x2="80" y2="10" stroke="#30363d" stroke-width="1"/>
      </svg>
      {% endif %}
    </div>

    <!-- Status badge -->
    <div class="market-card__status">
      {% if m.is_sparse %}
      <span class="badge badge--warn">&#9888; Sparse data</span>
      {% elif m.settled is none %}
      <span class="badge badge--open">&#9679; Open</span>
      {% elif m.settled %}
      <span class="badge badge--yes">&#9679; Settled YES</span>
      {% else %}
      <span class="badge badge--no">&#9679; Settled NO</span>
      {% endif %}
    </div>

    <div class="market-card__date">{{ m.date_range }}</div>
  </a>
  {% endfor %}
</div>
{% else %}
<div class="empty-state">
  <p>No data collected yet. Run <code>python -m kalshi_trader.scripts.collect_data</code> to start collecting.</p>
</div>
{% endif %}
{% endblock %}

{% block scripts %}
<script>
function filterMarkets(cat, btn) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.market-card').forEach(card => {
    const cardCat = card.querySelector('.market-card__meta').textContent.split('·')[0].trim();
    card.style.display = (cat === 'all' || cardCat === cat) ? '' : 'none';
  });
}
</script>
<style>
.section-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 16px; }
.summary-bar { font-size: 13px; color: #8b949e; }
.category-tabs { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.tab-btn { background: #161b22; border: 1px solid #30363d; color: #8b949e; padding: 4px 14px; border-radius: 16px; cursor: pointer; font-size: 13px; }
.tab-btn.active { background: #1f6feb; border-color: #1f6feb; color: white; }
.market-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.market-card { display: block; background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 14px; text-decoration: none; color: inherit; transition: border-color 0.15s; }
.market-card:hover { border-color: #58a6ff; }
.market-card--sparse { border-color: #f0883e; }
.market-card__ticker { font-size: 13px; font-weight: bold; color: #cdd9e5; margin-bottom: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.market-card__meta { font-size: 11px; color: #8b949e; margin-bottom: 8px; }
.market-card__sparkline { margin-bottom: 8px; }
.market-card__date { font-size: 10px; color: #8b949e; margin-top: 6px; }
.badge { font-size: 11px; padding: 2px 6px; border-radius: 10px; }
.badge--open { color: #3fb950; background: rgba(63,185,80,0.15); }
.badge--yes { color: #f85149; background: rgba(248,81,73,0.15); }
.badge--no { color: #8b949e; background: rgba(139,148,158,0.15); }
.badge--warn { color: #f0883e; background: rgba(240,136,62,0.15); }
.empty-state { text-align: center; padding: 60px 20px; color: #8b949e; }
</style>
{% endblock %}
```

- [ ] **Step 2: Verify page still returns 200**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_data_explorer_routes.py::test_page_data_explorer_returns_html -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/web/templates/data_explorer.html && git commit -m "feat: build data explorer coverage overview template"
```

---

### Task 6: Build market detail template

Replace the stub `data_explorer_market.html` with the full detail page (5 charts).

**Files:**
- Modify: `kalshi_trader/web/templates/data_explorer_market.html`

Chart.js is already loaded in `base.html` from CDN (`chart.js@4`).

- [ ] **Step 1: Replace stub with full template**

Overwrite `kalshi_trader/web/templates/data_explorer_market.html`:

```html
{% extends "base.html" %}
{% block title %}{{ ticker }} — Data Explorer{% endblock %}
{% block content %}
<div class="detail-header">
  <a href="/data-explorer" class="back-link">&#8592; Data Explorer</a>
  <h2 id="marketTitle">{{ ticker }}</h2>
  <div id="marketMeta" class="market-meta"></div>
</div>

<div id="loadingMsg" class="loading">Loading chart data...</div>
<div id="errorMsg" class="error-msg" style="display:none;"></div>

<div id="chartsContainer" style="display:none;">
  <div class="chart-card">
    <div class="chart-label">YES Mid Price (cents)</div>
    <canvas id="chartPrice"></canvas>
  </div>
  <div class="chart-row">
    <div class="chart-card">
      <div class="chart-label">Bid/Ask Spread (cents)</div>
      <canvas id="chartSpread"></canvas>
    </div>
    <div class="chart-card">
      <div class="chart-label">Volume / Open Interest</div>
      <canvas id="chartVolume"></canvas>
    </div>
  </div>
  <div class="chart-card">
    <div class="chart-label">Snapshots per Hour (gaps = collection issues)</div>
    <canvas id="chartSnapshots"></canvas>
  </div>
</div>
{% endblock %}

{% block scripts %}
<script>
(function() {
  const ticker = {{ ticker | tojson }};
  const CHART_DEFAULTS = {
    responsive: true,
    animation: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: '#8b949e', maxTicksLimit: 8, maxRotation: 0 }, grid: { color: '#21262d' } },
      y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } },
    },
  };

  function fmtTime(ts) {
    return new Date(ts * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  function bucketByHour(snapshots) {
    const counts = {};
    snapshots.forEach(s => {
      const h = Math.floor(s.timestamp / 3600) * 3600;
      counts[h] = (counts[h] || 0) + 1;
    });
    return counts;
  }

  function setStatus(settled) {
    if (settled === null || settled === undefined) return '<span class="badge badge--open">&#9679; Open</span>';
    if (settled) return '<span class="badge badge--yes">&#9679; Settled YES</span>';
    return '<span class="badge badge--no">&#9679; Settled NO</span>';
  }

  fetch('/api/v1/data-explorer/market/' + encodeURIComponent(ticker))
    .then(r => {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(snaps => {
      document.getElementById('loadingMsg').style.display = 'none';

      if (!snaps || snaps.length === 0) {
        document.getElementById('errorMsg').textContent = 'No data available for this market.';
        document.getElementById('errorMsg').style.display = '';
        return;
      }

      // Update header meta
      const latest = snaps[snaps.length - 1];
      document.getElementById('marketMeta').innerHTML =
        snaps.length + ' snapshots &middot; ' + setStatus(latest.settled);

      const labels = snaps.map(s => fmtTime(s.timestamp));

      // 1. YES Mid Price — with inline settlement marker (no external plugins needed)
      const midData = snaps.map(s => s.mid_price);
      const settledIdx = snaps.findIndex(s => s.settled !== null && s.settled !== undefined);
      const settlementLinePlugin = {
        id: 'settlementLine',
        afterDraw(chart) {
          if (settledIdx < 0) return;
          const { ctx, chartArea, scales } = chart;
          const x = scales.x.getPixelForValue(settledIdx);
          ctx.save();
          ctx.beginPath();
          ctx.moveTo(x, chartArea.top);
          ctx.lineTo(x, chartArea.bottom);
          ctx.lineWidth = 1;
          ctx.strokeStyle = '#3fb950';
          ctx.setLineDash([4, 4]);
          ctx.stroke();
          ctx.restore();
        }
      };
      new Chart(document.getElementById('chartPrice'), {
        type: 'line',
        plugins: [settlementLinePlugin],
        data: { labels, datasets: [{ data: midData, borderColor: '#58a6ff', borderWidth: 1.5, pointRadius: 0, tension: 0.1, spanGaps: true }] },
        options: { ...CHART_DEFAULTS, scales: { ...CHART_DEFAULTS.scales, y: { ...CHART_DEFAULTS.scales.y, min: 0, max: 100 } } },
      });

      // 2. Spread
      new Chart(document.getElementById('chartSpread'), {
        type: 'line',
        data: { labels, datasets: [{ data: snaps.map(s => s.spread), borderColor: '#d2a8ff', borderWidth: 1.5, pointRadius: 0, tension: 0.1, spanGaps: true }] },
        options: CHART_DEFAULTS,
      });

      // 3. Volume / Open Interest
      new Chart(document.getElementById('chartVolume'), {
        type: 'bar',
        data: {
          labels,
          datasets: [
            { label: 'Volume', data: snaps.map(s => s.volume), backgroundColor: 'rgba(31,111,235,0.7)' },
            { label: 'Open Interest', data: snaps.map(s => s.open_interest), backgroundColor: 'rgba(139,148,158,0.5)' },
          ]
        },
        options: { ...CHART_DEFAULTS, plugins: { legend: { display: true, labels: { color: '#8b949e' } } } },
      });

      // 4. Snapshots per hour
      const hourBuckets = bucketByHour(snaps);
      const hourLabels = Object.keys(hourBuckets).sort().map(h => fmtTime(parseInt(h)));
      const hourCounts = Object.keys(hourBuckets).sort().map(h => hourBuckets[h]);
      const hourColors = hourCounts.map(c => c >= 5 ? 'rgba(63,185,80,0.7)' : 'rgba(240,136,62,0.7)');
      new Chart(document.getElementById('chartSnapshots'), {
        type: 'bar',
        data: { labels: hourLabels, datasets: [{ data: hourCounts, backgroundColor: hourColors }] },
        options: CHART_DEFAULTS,
      });

      document.getElementById('chartsContainer').style.display = '';
    })
    .catch(err => {
      document.getElementById('loadingMsg').style.display = 'none';
      document.getElementById('errorMsg').textContent = 'Failed to load data: ' + err.message;
      document.getElementById('errorMsg').style.display = '';
    });
})();
</script>
<style>
.detail-header { margin-bottom: 20px; }
.back-link { color: #58a6ff; text-decoration: none; font-size: 13px; display: block; margin-bottom: 8px; }
.back-link:hover { text-decoration: underline; }
.market-meta { font-size: 13px; color: #8b949e; margin-top: 4px; }
.loading { color: #8b949e; padding: 20px 0; }
.error-msg { color: #f85149; padding: 20px 0; }
.chart-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; margin-bottom: 16px; }
.chart-label { font-size: 12px; color: #8b949e; margin-bottom: 12px; }
.chart-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.badge { font-size: 12px; padding: 2px 8px; border-radius: 10px; }
.badge--open { color: #3fb950; background: rgba(63,185,80,0.15); }
.badge--yes { color: #f85149; background: rgba(248,81,73,0.15); }
.badge--no { color: #8b949e; background: rgba(139,148,158,0.15); }
</style>
{% endblock %}
```

- [ ] **Step 2: Verify page still returns 200**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/test_data_explorer_routes.py::test_page_data_explorer_market_returns_html -v
```
Expected: PASS.

- [ ] **Step 3: Run full test suite**

```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -m pytest tests/ -v --tb=short
```
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
cd /home/mycool/claudetesting/kalshi_trader && git add kalshi_trader/web/templates/data_explorer_market.html && git commit -m "feat: build market detail template with 5 Chart.js charts"
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
from kalshi_trader.scripts.collect_data import main as collect_main
from kalshi_trader.scripts.run_research import main as research_main
print('all imports ok')
"
```

And verify the config change:
```bash
cd /home/mycool/claudetesting/kalshi_trader && venv/bin/python -c "from kalshi_trader.config import load_config; print(load_config().dashboard_port)"
```
Expected: `55055`
