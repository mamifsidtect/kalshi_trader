from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os

router = APIRouter()
_templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_templates_dir)


@router.get("/positions", response_class=HTMLResponse)
async def positions_page(request: Request):
    data_service = request.app.state.data_service
    positions = data_service.get_positions()
    return templates.TemplateResponse(request, "positions.html", {"positions": positions})


@router.get("/api/v1/positions")
async def api_positions(request: Request):
    return request.app.state.data_service.get_positions()


@router.get("/api/v1/signals")
async def api_signals(request: Request):
    return request.app.state.data_service.get_signals()
