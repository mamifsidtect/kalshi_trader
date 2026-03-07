import time
import logging
from typing import List, Optional, Dict, Any
from kalshi_trader.config import KalshiConfig
from kalshi_trader.utils.logger import get_logger

try:
    from kalshi_python import ApiClient, Configuration, MarketsApi, PortfolioApi
    KALSHI_AVAILABLE = True
except ImportError:
    KALSHI_AVAILABLE = False


class KalshiClient:
    MAX_RETRIES = 3
    RETRY_BACKOFF = 2.0  # seconds, doubled each retry

    def __init__(self, config: KalshiConfig):
        self.config = config
        self.logger = get_logger(__name__, config.log_level)
        self._api, self._portfolio_api = self._init_api()

    def _init_api(self):
        if not KALSHI_AVAILABLE:
            self.logger.warning("kalshi-python not installed; client will be non-functional")
            return None, None
        cfg = Configuration()
        cfg.host = (
            "https://demo-api.kalshi.co/trade-api/v2"
            if self.config.kalshi_environment == "demo"
            else "https://trading-api.kalshi.com/trade-api/v2"
        )
        client = ApiClient(cfg)
        key_file = self.config.kalshi_api_key_file
        key_id = self.config.kalshi_api_key_id
        if key_file and key_id:
            try:
                import os as _os
                client.set_kalshi_auth(key_id, _os.path.expanduser(key_file))
            except Exception as e:
                self.logger.warning(f"Failed to load Kalshi auth key: {e}")
                return None, None
        else:
            self.logger.warning("Kalshi API credentials not configured (need KALSHI_API_KEY_FILE + KALSHI_API_KEY_ID)")
            return None, None
        return MarketsApi(client), PortfolioApi(client)

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

    def _require_api(self) -> None:
        if self._api is None:
            raise RuntimeError("Kalshi API not available — install kalshi-python and set credentials")

    def _require_portfolio_api(self) -> None:
        if self._portfolio_api is None:
            raise RuntimeError("Kalshi API not available — install kalshi-python and set credentials")

    def get_markets(self, category: Optional[str] = None, status: str = "open") -> List[Dict]:
        self._require_api()
        resp = self._with_retry(self._api.get_markets, status=status)
        markets = resp.markets or []
        if category:
            markets = [m for m in markets if getattr(m, "category", "") == category]
        return [self._market_to_dict(m) for m in markets]

    def get_orderbook(self, ticker: str) -> Dict[str, Any]:
        self._require_api()
        resp = self._with_retry(self._api.get_market_orderbook, ticker)
        ob = resp.orderbook
        return {
            "yes": [[l.price, l.quantity] for l in (ob.yes or [])],
            "no": [[l.price, l.quantity] for l in (ob.no or [])],
        }

    def get_market_history(self, ticker: str, start_ts: int, end_ts: int) -> List[Dict]:
        self._require_api()
        resp = self._with_retry(
            self._api.get_market_candlesticks, ticker, ticker,
            start_ts=start_ts, end_ts=end_ts
        )
        return [
            {"ts": c.start_ts, "yes_price": c.close}
            for c in (resp.candlesticks or [])
        ]

    def place_order(self, ticker: str, side: str, price: int, count: int) -> Dict:
        self._require_portfolio_api()
        from kalshi_python.models import CreateOrderRequest
        req = CreateOrderRequest(
            ticker=ticker, action="buy",
            side=side, type="limit",
            yes_price=price if side == "yes" else 100 - price,
            count=count,
        )
        resp = self._with_retry(self._portfolio_api.create_order, create_order_request=req)
        return {"order_id": resp.order.order_id, "status": resp.order.status}

    def cancel_order(self, order_id: str) -> bool:
        self._require_portfolio_api()
        self._with_retry(self._portfolio_api.cancel_order, order_id)
        return True

    def get_positions(self) -> List[Dict]:
        self._require_portfolio_api()
        resp = self._with_retry(self._portfolio_api.get_positions)
        positions = []
        for p in (resp.positions or []):
            net = p.position or 0
            positions.append({
                "ticker": p.ticker,
                "side": "yes" if net >= 0 else "no",
                "quantity": abs(net),
                "avg_price": None,
            })
        return positions

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
