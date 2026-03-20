#!/usr/bin/env python3
"""
Standalone web dashboard — browse data, run backtests, and explore signals
without starting the live trading loop.

Usage:
    python -m kalshi_trader.scripts.run_dashboard
    python -m kalshi_trader.scripts.run_dashboard --port 8080
"""
import argparse
import uvicorn
from kalshi_trader.config import load_config
from kalshi_trader.web.app import create_app
from kalshi_trader.utils.logger import get_logger


def main():
    parser = argparse.ArgumentParser(description="Run the Kalshi Trader dashboard standalone")
    parser.add_argument("--port", type=int, default=None,
                        help="Port to serve on (default: from config or 55055)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    args = parser.parse_args()

    cfg = load_config()
    port = args.port or cfg.dashboard_port
    logger = get_logger("run_dashboard", cfg.log_level)

    app = create_app(cfg)
    logger.info(f"Dashboard starting at http://localhost:{port}")
    uvicorn.run(app, host=args.host, port=port, log_level="info")


if __name__ == "__main__":
    main()
