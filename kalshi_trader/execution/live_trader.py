from typing import Dict, Any
from kalshi_trader.data.models import Signal
from kalshi_trader.config import KalshiConfig
from kalshi_trader.utils.logger import get_logger


class LiveTrader:
    def __init__(self, client, config: KalshiConfig):
        self.client = client
        self.config = config
        self.logger = get_logger(__name__, config.log_level)

    def execute(self, signal: Signal, current_price: int) -> Dict[str, Any]:
        self.logger.info(
            f"[LIVE] Placing {signal.direction.upper()} order: "
            f"{signal.size}x {signal.ticker} @ {current_price}c"
        )
        try:
            result = self.client.place_order(
                ticker=signal.ticker,
                side=signal.direction,
                price=current_price,
                count=signal.size,
            )
            self.logger.info(f"[LIVE] Order placed: {result}")
            return result
        except Exception as e:
            self.logger.error(f"[LIVE] Order failed for {signal.ticker}: {e}")
            return {"status": "rejected", "reason": str(e), "ticker": signal.ticker}

    def close_position(self, ticker: str) -> bool:
        try:
            positions = self.client.get_positions()
            matched = [p for p in positions if p["ticker"] == ticker]
            if not matched:
                self.logger.warning(f"[LIVE] No open position found for {ticker}")
                return False
            for pos in matched:
                self.client.place_order(
                    ticker=ticker, side=pos["side"],
                    price=99, count=pos["quantity"],
                )
            return True
        except Exception as e:
            self.logger.error(f"[LIVE] Failed to close {ticker}: {e}")
            return False
