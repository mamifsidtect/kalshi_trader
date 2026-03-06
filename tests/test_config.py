from kalshi_trader.config import KalshiConfig, load_config

def test_default_config():
    cfg = KalshiConfig()
    assert cfg.execution_mode == "paper"
    assert cfg.max_position_pct == 0.05
    assert cfg.daily_loss_limit_pct == 0.03
    assert cfg.dashboard_port == 8000

def test_load_config_from_env(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY", "test-key")
    monkeypatch.setenv("EXECUTION_MODE", "live")
    cfg = load_config()
    assert cfg.kalshi_api_key == "test-key"
    assert cfg.execution_mode == "live"
