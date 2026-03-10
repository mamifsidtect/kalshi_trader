from kalshi_trader.config import KalshiConfig, load_config
from kalshi_trader.utils.logger import get_logger
import logging

def test_get_logger_returns_logger():
    logger = get_logger("test.logger")
    assert isinstance(logger, logging.Logger)

def test_get_logger_no_duplicate_handlers():
    logger1 = get_logger("test.dedup")
    handler_count = len(logger1.handlers)
    logger2 = get_logger("test.dedup")
    assert len(logger2.handlers) == handler_count

def test_load_config_defaults_when_no_env(monkeypatch):
    monkeypatch.delenv("KALSHI_API_KEY", raising=False)
    monkeypatch.delenv("KALSHI_API_KEY_FILE", raising=False)
    monkeypatch.delenv("EXECUTION_MODE", raising=False)
    cfg = load_config()
    assert cfg.execution_mode == "paper"
    assert cfg.kalshi_api_key == ""

def test_load_config_invalid_execution_mode(monkeypatch):
    monkeypatch.delenv("KALSHI_API_KEY_FILE", raising=False)
    monkeypatch.setenv("EXECUTION_MODE", "invalid")
    import pytest
    with pytest.raises(ValueError, match="EXECUTION_MODE"):
        load_config()

def test_default_config():
    cfg = KalshiConfig()
    assert cfg.execution_mode == "paper"
    assert cfg.max_position_pct == 0.05
    assert cfg.daily_loss_limit_pct == 0.03
    assert cfg.dashboard_port == 55055

def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY", "test-key")
    monkeypatch.setenv("EXECUTION_MODE", "live")
    cfg = load_config()
    assert cfg.kalshi_api_key == "test-key"
    assert cfg.execution_mode == "live"
