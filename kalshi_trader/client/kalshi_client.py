import time
import logging
from typing import List, Optional, Dict, Any
from kalshi_trader.config import KalshiConfig
from kalshi_trader.utils.logger import get_logger

try:
    from kalshi_python import ApiClient, Configuration, MarketApi
    KALSHI_AVAILABLE = True
except ImportError:
    KALSHI_AVAILABLE = False


class KalshiClient:
    MAX_RETRIES = 3
    RETRY_BACKOFF = 2.0  # seconds, doubled each retry

    def __init__(self, config: KalshiConfig):
        self.config = config
        self.logger = get_logger(__name__, config.log_level)
        self._api = self._init_api()

    def _init_api(self):
        if not KALSHI_AVAILABLE:
            self.logger.warning("kalshi-python not installed; client will be non-functional")
            return None
        cfg = Configuration()
        cfg.host = (
            "https://demo-api.kalshi.co/trade-api/v2"
            if self.config.kalshi_environment == "demo"
            else "https://trading-api.kalshi.com/trade-api/v2"
        )
        client = ApiClient(cfg)
        client.set_default_header("Authorization", f"Bearer {self.config.kalshi_api_key}")
        return MarketApi(client)

    def _with_retry(self, fn, *args, **kwargs):
        delay = self.RETRY_BACKOFF
        last_exc = None
        for attempt in range(self.MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_exc = e
                self.logger.warning(f"API call failed (attempt {attempt+1}/{self.MAX_RETRIES}): {e}")
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
        raise last_exc

    def get_markets(self, category: Optional[str] = None, status: str = "open") -> List[Dict]:
        resp = self._with_retry(self._api.get_markets, status=status)
        markets = resp.markets or []
        if category:
            markets = [m for m in markets if getattr(m, "category", "") == category]
        return [self._market_to_dict(m) for m in markets]

    def get_orderbook(self, ticker: str) -> Dict[str, Any]:
        resp = self._with_retry(self._api.get_market_orderbook, ticker)
        ob = resp.orderbook
        return {
            "yes": [[l.price, l.quantity] for l in (ob.yes or [])],
            "no": [[l.price, l.quantity] for l in (ob.no or [])],
        }

    def get_market_history(self, ticker: str, start_ts: int, end_ts: int) -> List[Dict]:
        resp = self._with_retry(
            self._api.get_market_history, ticker,
            min_ts=start_ts, max_ts=end_ts
        )
        return [{"ts": h.ts, "yes_price": h.yes_price} for h in (resp.history or [])]

    def place_order(self, ticker: str, side: str, price: int, count: int) -> Dict:
        if self._api is None:
            raise RuntimeError("Kalshi API not available — install kalshi-python and set credentials")
        from kalshi_python.models import CreateOrderRequest
        req = CreateOrderRequest(
            ticker=ticker, action="buy",
            side=side, type="limit",
            yes_price=price if side == "yes" else 100 - price,
            count=count,
        )
        resp = self._with_retry(self._api.create_order, req)
        return {"order_id": resp.order.order_id, "status": resp.order.status}

    def cancel_order(self, order_id: str) -> bool:
        self._with_retry(self._api.cancel_order, order_id)
        return True

    def get_positions(self) -> List[Dict]:
        resp = self._with_retry(self._api.get_positions)
        return [
            {"ticker": p.ticker, "side": p.side, "quantity": p.quantity,
             "avg_price": p.average_price}
            for p in (resp.market_positions or [])
        ]

    def _market_to_dict(self, m) -> Dict:
        _ct = getattr(m, "close_time", None)
        return {
            "ticker": m.ticker,
            "title": getattr(m, "title", ""),
            "category": getattr(m, "category", ""),
            "yes_bid": getattr(m, "yes_bid", None),
            "yes_ask": getattr(m, "yes_ask", None),
            "volume": getattr(m, "volume", 0),
            "open_interest": getattr(m, "open_interest", 0),
            "status": getattr(m, "status", ""),
            "close_time": _ct.isoformat() if hasattr(_ct, "isoformat") else str(_ct) if _ct else "",
        }
