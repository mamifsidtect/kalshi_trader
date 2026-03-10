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
