"""
Promotion bridge: persist and load the best sweep configs per strategy.

Promoted configs are saved to {config.data_dir}/promoted/<StrategyName>.json
by the parameter sweeper. run_live.py loads them at startup to instantiate
only strategies with backtest-validated parameters.
"""
import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict

from kalshi_trader.config import KalshiConfig
from kalshi_trader.research.backtester import BacktestResult
from kalshi_trader.utils.logger import get_logger


def _promoted_dir(config: KalshiConfig) -> str:
    return os.path.join(config.data_dir, "promoted")


def save_promoted_config(
    config: KalshiConfig,
    strategy_name: str,
    params: Dict[str, Any],
    backtest_result: BacktestResult,
) -> str:
    """Save promoted config to disk. Returns the file path written."""
    log = get_logger(__name__, config.log_level)
    promoted_dir = _promoted_dir(config)
    os.makedirs(promoted_dir, exist_ok=True)

    data = {
        "strategy_name": strategy_name,
        "params": params,
        "backtest": {
            "sharpe": backtest_result.sharpe,
            "win_rate": backtest_result.win_rate,
            "total_pnl": backtest_result.total_pnl,
            "total_trades": backtest_result.total_trades,
        },
        "promoted_at": datetime.now(timezone.utc).isoformat(),
    }

    path = os.path.join(promoted_dir, f"{strategy_name}.json")
    fd, tmp_path = tempfile.mkstemp(dir=promoted_dir, suffix=".tmp")
    try:
        os.write(fd, json.dumps(data, indent=2).encode())
    finally:
        os.close(fd)
    os.replace(tmp_path, path)

    log.info(f"Promoted {strategy_name} config to {path}")
    return path
