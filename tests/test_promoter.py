import json
import os
import tempfile
from kalshi_trader.config import KalshiConfig
from kalshi_trader.research.backtester import BacktestResult


def _make_config(tmp_dir):
    cfg = KalshiConfig()
    cfg.data_dir = tmp_dir
    return cfg


def _make_backtest_result():
    return BacktestResult(
        strategy_name="MarketMaker",
        total_trades=23,
        win_rate=0.62,
        total_pnl=14.50,
        sharpe=0.85,
        max_drawdown=3.20,
        avg_hold_bars=3600.0,
    )


def test_save_promoted_config_writes_json():
    from kalshi_trader.research.promoter import save_promoted_config
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        params = {"min_spread": 3, "min_volume": 50}
        bt = _make_backtest_result()
        save_promoted_config(cfg, "MarketMaker", params, bt)

        path = os.path.join(tmp, "promoted", "MarketMaker.json")
        assert os.path.exists(path)
        with open(path) as f:
            data = json.load(f)
        assert data["strategy_name"] == "MarketMaker"
        assert data["params"] == params
        assert data["backtest"]["sharpe"] == 0.85
        assert data["backtest"]["win_rate"] == 0.62
        assert data["backtest"]["total_pnl"] == 14.50
        assert data["backtest"]["total_trades"] == 23
        assert "promoted_at" in data


def test_save_promoted_config_overwrites_existing():
    from kalshi_trader.research.promoter import save_promoted_config
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        bt = _make_backtest_result()
        save_promoted_config(cfg, "MarketMaker", {"min_spread": 3}, bt)
        save_promoted_config(cfg, "MarketMaker", {"min_spread": 7}, bt)

        path = os.path.join(tmp, "promoted", "MarketMaker.json")
        with open(path) as f:
            data = json.load(f)
        assert data["params"]["min_spread"] == 7
