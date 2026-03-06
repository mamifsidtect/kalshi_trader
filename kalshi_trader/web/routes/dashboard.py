from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os

router = APIRouter()
_templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_templates_dir)


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    data_service = request.app.state.data_service
    summary = data_service.get_summary()
    return templates.TemplateResponse(request, "dashboard.html", {"summary": summary})
