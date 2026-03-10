import os
import logging
from dataclasses import dataclass

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass


@dataclass
class KalshiConfig:
    # Auth
    kalshi_api_key: str = ""
    kalshi_api_key_id: str = ""
    kalshi_api_key_file: str = ""   # path to file containing the API key
    kalshi_environment: str = "demo"  # "demo" or "prod"

    # Execution
    execution_mode: str = "paper"  # "paper" or "live"

    # Risk
    max_position_pct: float = 0.05
    daily_loss_limit_pct: float = 0.03
    max_total_exposure_pct: float = 0.30
    max_category_exposure_pct: float = 0.30

    # Research gates
    min_backtest_sharpe: float = 0.5
    min_backtest_win_rate: float = 0.52

    # Data collection
    collection_interval_seconds: int = 60
    data_dir: str = "data"

    # Dashboard
    dashboard_port: int = 8000
    dashboard_enabled: bool = True

    # Logging
    log_level: str = "INFO"
    log_file: str = "kalshi_trader.log"

    # Exit conditions
    exit_profit_cents: int = 0    # 0 = disabled; close position when profit >= N cents
    exit_time_hours: int = 0      # 0 = disabled; close position after N hours

    # Polymarket integration
    ticker_mappings_file: str = ""  # path to JSON: {kalshi_ticker: polymarket_condition_id}

    def __repr__(self) -> str:
        key_preview = self.kalshi_api_key[:4] + "..." if self.kalshi_api_key else "(not set)"
        return (
            f"KalshiConfig(environment={self.kalshi_environment!r}, "
            f"execution_mode={self.execution_mode!r}, "
            f"kalshi_api_key={key_preview!r}, ...)"
        )


def load_config() -> KalshiConfig:
    cfg = KalshiConfig()
    if os.getenv("KALSHI_API_KEY"):
        cfg.kalshi_api_key = os.getenv("KALSHI_API_KEY")
    if os.getenv("KALSHI_API_KEY_ID"):
        cfg.kalshi_api_key_id = os.getenv("KALSHI_API_KEY_ID")
    if os.getenv("KALSHI_API_KEY_FILE"):
        cfg.kalshi_api_key_file = os.getenv("KALSHI_API_KEY_FILE")
    if os.getenv("KALSHI_ENVIRONMENT"):
        cfg.kalshi_environment = os.getenv("KALSHI_ENVIRONMENT")
    if os.getenv("EXECUTION_MODE"):
        cfg.execution_mode = os.getenv("EXECUTION_MODE")
    if os.getenv("LOG_LEVEL"):
        cfg.log_level = os.getenv("LOG_LEVEL")
    if os.getenv("EXIT_PROFIT_CENTS"):
        cfg.exit_profit_cents = int(os.getenv("EXIT_PROFIT_CENTS"))
    if os.getenv("EXIT_TIME_HOURS"):
        cfg.exit_time_hours = int(os.getenv("EXIT_TIME_HOURS"))
    if os.getenv("TICKER_MAPPINGS_FILE"):
        cfg.ticker_mappings_file = os.getenv("TICKER_MAPPINGS_FILE")

    VALID_EXECUTION_MODES = {"paper", "live"}
    VALID_ENVIRONMENTS = {"demo", "prod"}
    if cfg.execution_mode not in VALID_EXECUTION_MODES:
        raise ValueError(f"EXECUTION_MODE must be one of {VALID_EXECUTION_MODES}, got: {cfg.execution_mode!r}")
    if cfg.kalshi_environment not in VALID_ENVIRONMENTS:
        raise ValueError(f"KALSHI_ENVIRONMENT must be one of {VALID_ENVIRONMENTS}, got: {cfg.kalshi_environment!r}")

    _configure_root_logging(cfg)
    return cfg


def _configure_root_logging(cfg: KalshiConfig) -> None:
    """Attach a file handler to the root logger so all module loggers write to the log file."""
    root = logging.getLogger()
    # Avoid adding duplicate file handlers on repeated load_config() calls
    if any(isinstance(h, logging.FileHandler) and h.baseFilename.endswith(cfg.log_file)
           for h in root.handlers):
        return
    if cfg.log_file:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        fh = logging.FileHandler(cfg.log_file)
        fh.setFormatter(fmt)
        fh.setLevel(getattr(logging, cfg.log_level.upper(), logging.INFO))
        root.setLevel(getattr(logging, cfg.log_level.upper(), logging.INFO))
        root.addHandler(fh)
