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


def test_load_promoted_configs_reads_saved():
    from kalshi_trader.research.promoter import save_promoted_config, load_promoted_configs
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        bt = _make_backtest_result()
        save_promoted_config(cfg, "MarketMaker", {"min_spread": 3, "min_volume": 50}, bt)
        save_promoted_config(cfg, "Directional", {"confidence_threshold": 0.7}, bt)

        promoted = load_promoted_configs(cfg)
        assert "MarketMaker" in promoted
        assert "Directional" in promoted
        assert promoted["MarketMaker"] == {"min_spread": 3, "min_volume": 50}
        assert promoted["Directional"] == {"confidence_threshold": 0.7}


def test_load_promoted_configs_missing_dir():
    from kalshi_trader.research.promoter import load_promoted_configs
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        promoted = load_promoted_configs(cfg)
        assert promoted == {}


def test_load_promoted_configs_skips_malformed(caplog):
    from kalshi_trader.research.promoter import save_promoted_config, load_promoted_configs
    import logging
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        bt = _make_backtest_result()
        # Save one valid config
        save_promoted_config(cfg, "MarketMaker", {"min_spread": 3}, bt)
        # Write one malformed file
        bad_path = os.path.join(tmp, "promoted", "Bad.json")
        with open(bad_path, "w") as f:
            f.write("{not valid json")

        with caplog.at_level(logging.WARNING):
            promoted = load_promoted_configs(cfg)

        assert "MarketMaker" in promoted
        assert "Bad" not in promoted
        assert any("malformed" in r.message.lower() for r in caplog.records)


def test_sweeper_auto_promotes_best_config():
    """ParameterSweeper.sweep() should auto-save promoted config when best exists."""
    from kalshi_trader.research.promoter import load_promoted_configs
    from kalshi_trader.research.parameter_sweeper import ParameterSweeper
    from kalshi_trader.data.models import MarketSnapshot, ExternalSignals
    import time

    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        # Use a tiny grid that will produce at least one promoted result
        # MarketMaker with low min_spread on high-spread data should trade and pass gate
        snaps = []
        for i in range(20):
            snaps.append(MarketSnapshot(
                ticker="T", timestamp=1700000000 + i * 60,
                yes_bid=40, yes_ask=50, no_bid=50, no_ask=60,
                volume=500, open_interest=200, category="financial",
                settled=True if i == 19 else None,
            ))
        signals_obj = ExternalSignals(timestamp=int(time.time()))
        sweeper = ParameterSweeper(cfg)
        report = sweeper.sweep(
            "MarketMaker", snaps, lambda ts: signals_obj,
            param_grid={"min_spread": [1], "min_volume": [0], "contracts_per_quote": [1],
                        "exit_profit_cents": [0], "exit_time_hours": [0]},
        )
        # If the sweep found a promotable config, it should be saved
        if report.best:
            promoted = load_promoted_configs(cfg)
            assert "MarketMaker" in promoted


def test_load_and_instantiate_strategies():
    """Promoted configs should produce working strategy instances."""
    from kalshi_trader.research.promoter import save_promoted_config, load_promoted_configs
    from kalshi_trader.research.parameter_sweeper import STRATEGY_CLASSES
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        bt = _make_backtest_result()
        save_promoted_config(cfg, "MarketMaker", {"min_spread": 5, "min_volume": 100}, bt)
        save_promoted_config(cfg, "Directional", {"confidence_threshold": 0.7, "contracts": 1}, bt)

        promoted = load_promoted_configs(cfg)
        strategies = []
        for name, params in promoted.items():
            cls = STRATEGY_CLASSES.get(name)
            assert cls is not None, f"Unknown strategy: {name}"
            instance = cls(**params)
            strategies.append(instance)

        assert len(strategies) == 2
        names = {s.name for s in strategies}
        assert "MarketMaker" in names
        assert "Directional" in names


def test_load_skips_incompatible_params():
    """Strategy with unknown params should be skipped, not crash."""
    from kalshi_trader.research.promoter import save_promoted_config, load_promoted_configs
    from kalshi_trader.research.parameter_sweeper import STRATEGY_CLASSES
    from kalshi_trader.strategies.arbitrage import ArbitrageStrategy
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        bt = _make_backtest_result()
        # Save a config with an invalid param name
        save_promoted_config(cfg, "MarketMaker", {"nonexistent_param": 99}, bt)
        # Save a valid config too
        save_promoted_config(cfg, "Directional", {"confidence_threshold": 0.7}, bt)

        promoted = load_promoted_configs(cfg)
        strategies = []
        for name, params in promoted.items():
            cls = STRATEGY_CLASSES.get(name)
            if cls is None:
                continue
            try:
                instance = cls(**params)
            except TypeError:
                continue
            strategies.append(instance)

        # Only Directional should load; MarketMaker should be skipped
        assert len(strategies) == 1
        assert strategies[0].name == "Directional"


def test_no_promoted_configs_returns_empty():
    """When no promoted configs exist, load returns empty and instantiation loop produces nothing."""
    from kalshi_trader.research.promoter import load_promoted_configs
    from kalshi_trader.research.parameter_sweeper import STRATEGY_CLASSES
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _make_config(tmp)
        promoted = load_promoted_configs(cfg)
        assert promoted == {}

        strategies = []
        for name, params in promoted.items():
            cls = STRATEGY_CLASSES.get(name)
            if cls:
                strategies.append(cls(**params))
        assert len(strategies) == 0
