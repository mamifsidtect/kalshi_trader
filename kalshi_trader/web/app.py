from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os
from kalshi_trader.config import KalshiConfig
from kalshi_trader.web.services.data_service import DataService
from kalshi_trader.web.routes import dashboard, positions, research, markets
from kalshi_trader.web.routes import data_explorer
from kalshi_trader.web.services.data_explorer_service import DataExplorerService


def create_app(config: KalshiConfig, paper_trader=None, signal_feed=None) -> FastAPI:
    app = FastAPI(title="Kalshi Trader Dashboard")

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    app.state.config = config
    app.state.data_service = DataService(config, paper_trader=paper_trader, signal_feed=signal_feed)
    app.state.data_explorer_service = DataExplorerService(config)

    app.include_router(dashboard.router)
    app.include_router(positions.router)
    app.include_router(research.router)
    app.include_router(markets.router)
    app.include_router(data_explorer.router)

    return app
