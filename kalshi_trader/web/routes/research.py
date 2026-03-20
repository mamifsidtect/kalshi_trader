from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
import os, time

router = APIRouter()
_templates_dir = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_templates_dir)


class BacktestRequest(BaseModel):
    strategy: str
    days: int = 7
    min_spread: Optional[int] = 3
    confidence_threshold: Optional[float] = 0.6
    min_edge_cents: Optional[int] = 5
    min_divergence: Optional[float] = 0.05


class SweepRequest(BaseModel):
    strategy: str
    days: int = 7


@router.get("/research/signals", response_class=HTMLResponse)
async def signal_explorer(request: Request):
    return templates.TemplateResponse(request, "research_signals.html")


@router.get("/research/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    return templates.TemplateResponse(request, "research_backtest.html")


@router.post("/api/v1/research/backtest")
async def run_backtest(req: BacktestRequest, request: Request):
    from kalshi_trader.strategies.market_maker import MarketMakerStrategy
    from kalshi_trader.strategies.directional import DirectionalStrategy
    from kalshi_trader.strategies.single_condition_arb import SingleConditionArbStrategy
    from kalshi_trader.strategies.bregman_divergence import BregmanDivergenceStrategy
    from kalshi_trader.research.backtester import Backtester
    from kalshi_trader.data.models import ExternalSignals

    cfg = request.app.state.config
    strategy_map = {
        "MarketMaker": MarketMakerStrategy(min_spread=req.min_spread or 3),
        "Directional": DirectionalStrategy(confidence_threshold=req.confidence_threshold or 0.6),
        "SingleConditionArb": SingleConditionArbStrategy(min_edge_cents=req.min_edge_cents or 5),
        "BregmanDivergence": BregmanDivergenceStrategy(min_divergence=req.min_divergence or 0.05),
    }
    strategy = strategy_map.get(req.strategy)
    if not strategy:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": f"Unknown strategy: {req.strategy}"}, status_code=422)

    data_service = request.app.state.data_service
    snapshots = data_service.get_recent_snapshots(days=req.days)
    if not snapshots:
        return {"error": "no_data", "message": "No snapshots found. Run data collection first."}

    blank_signals = ExternalSignals(timestamp=int(time.time()))
    bt = Backtester(cfg)
    result = bt.run(strategy, snapshots, lambda ts: blank_signals)
    return {
        "strategy": result.strategy_name,
        "total_trades": result.total_trades,
        "win_rate": result.win_rate,
        "total_pnl": result.total_pnl,
        "sharpe": result.sharpe,
        "max_drawdown": result.max_drawdown,
        "meets_promotion_gate": result.meets_promotion_gate(cfg),
        "trade_log": result.trade_log[:50],
    }


@router.post("/api/v1/research/sweep")
async def run_sweep(req: SweepRequest, request: Request):
    from kalshi_trader.research.parameter_sweeper import ParameterSweeper
    from kalshi_trader.data.models import ExternalSignals

    cfg = request.app.state.config
    data_service = request.app.state.data_service
    snapshots = data_service.get_recent_snapshots(days=req.days)
    if not snapshots:
        return {"error": "no_data", "message": "No snapshots found. Run data collection first."}

    blank_signals = ExternalSignals(timestamp=int(time.time()))
    sweeper = ParameterSweeper(cfg)
    report = sweeper.sweep(req.strategy, snapshots, lambda ts: blank_signals)

    top_results = []
    for r in report.all_results[:20]:
        top_results.append({
            "params": r.params,
            "backtest": {
                "total_trades": r.backtest.total_trades,
                "win_rate": r.backtest.win_rate,
                "total_pnl": r.backtest.total_pnl,
                "sharpe": r.backtest.sharpe,
                "max_drawdown": r.backtest.max_drawdown,
            },
            "promoted": r.promoted,
        })

    best = None
    if report.best:
        best = {
            "params": report.best.params,
            "backtest": {
                "total_trades": report.best.backtest.total_trades,
                "win_rate": report.best.backtest.win_rate,
                "total_pnl": report.best.backtest.total_pnl,
                "sharpe": report.best.backtest.sharpe,
                "max_drawdown": report.best.backtest.max_drawdown,
            },
        }

    return {
        "strategy": req.strategy,
        "total_combinations": report.total_combinations,
        "promoted_count": len(report.promoted_results),
        "best": best,
        "top_results": top_results,
    }


@router.get("/api/v1/research/signals")
async def signal_accuracy(request: Request, type: str = "price_momentum"):
    from kalshi_trader.research.signal_tester import SignalTester
    cfg = request.app.state.config
    tester = SignalTester(cfg)
    snapshots = request.app.state.data_service.get_recent_snapshots(days=7)
    if type == "price_momentum":
        return {"type": type, "accuracy": tester.test_price_momentum(snapshots), "n": len(snapshots)}
    elif type == "spread_liquidity":
        return {"type": type, **tester.test_spread_liquidity(snapshots)}
    return {"error": "unknown type"}
