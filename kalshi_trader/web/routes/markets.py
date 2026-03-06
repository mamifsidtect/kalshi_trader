from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import os

router = APIRouter()
_templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_templates_dir)


@router.get("/research/markets", response_class=HTMLResponse)
async def market_browser(request: Request):
    return templates.TemplateResponse(request, "research_markets.html")


@router.get("/api/v1/markets")
async def api_markets(request: Request, category: Optional[str] = None):
    return request.app.state.data_service.get_markets(category=category)
