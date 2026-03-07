#!/usr/bin/env python3
"""
Entry point: continuously collect Kalshi market data and external signals.

Usage:
    python -m kalshi_trader.scripts.collect_data
    KALSHI_API_KEY=xxx python -m kalshi_trader.scripts.collect_data
"""
import time
from kalshi_trader.config import load_config
from kalshi_trader.client.kalshi_client import KalshiClient
from kalshi_trader.data.market_collector import MarketCollector
from kalshi_trader.data.external_signals import ExternalSignalCollector
from kalshi_trader.utils.logger import get_logger


def main():
    cfg = load_config()
    logger = get_logger("collect_data", cfg.log_level)
    client = KalshiClient(cfg)
    market_collector = MarketCollector(client, cfg)
    signal_collector = ExternalSignalCollector(cfg)

    logger.info(f"Starting data collection (interval={cfg.collection_interval_seconds}s)")
    while True:
        try:
            snapshots = market_collector.collect_once()
            signals = signal_collector.collect()
            logger.info(
                f"Collected {len(snapshots)} markets, "
                f"{len(signals.news_headlines)} news items"
            )
        except KeyboardInterrupt:
            logger.info("Collection stopped by user")
            break
        except Exception as e:
            logger.error(f"Collection error: {e}")
        time.sleep(cfg.collection_interval_seconds)


if __name__ == "__main__":
    main()
