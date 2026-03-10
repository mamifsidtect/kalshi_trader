import json, os, time, uuid
from typing import List, Dict, Any, Optional
from kalshi_trader.data.models import Signal
from kalshi_trader.config import KalshiConfig
from kalshi_trader.utils.logger import get_logger


class PaperTrader:
    def __init__(self, config: KalshiConfig, initial_bankroll: float = 1000.0):
        self.config = config
        self.bankroll = initial_bankroll
        self.realized_pnl: float = 0.0
        self.logger = get_logger(__name__, config.log_level)
        self._positions: Dict[str, Dict] = {}
        self._order_log: List[Dict] = []
        self._log_path = os.path.join(config.data_dir, "paper_orders.json")
        os.makedirs(config.data_dir, exist_ok=True)

    def execute(self, signal: Signal, current_price: int) -> Dict[str, Any]:
        if signal.ticker in self._positions:
            self.logger.warning(
                f"[PAPER] Position already open for {signal.ticker}; skipping duplicate order"
            )
            return {"status": "rejected", "reason": "position already open", "ticker": signal.ticker}
        cost = signal.size * (current_price / 100.0)
        order = {
            "order_id": f"paper-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}",
            "ticker": signal.ticker,
            "direction": signal.direction,
            "size": signal.size,
            "entry_price": current_price,
            "cost": cost,
            "strategy": signal.strategy_name,
            "reason": signal.reason,
            "timestamp": int(time.time()),
            "status": "filled",
        }
        self._positions[signal.ticker] = order
        self.bankroll -= cost
        self._order_log.append(order)
        self._persist_log()
        self.logger.info(
            f"[PAPER] Filled {signal.direction.upper()} {signal.size}x "
            f"{signal.ticker} @ {current_price}c (cost=${cost:.2f})"
        )
        return order

    def close_position(self, ticker: str, exit_price: int) -> Optional[Dict]:
        if ticker not in self._positions:
            return None
        pos = self._positions.pop(ticker)
        if pos["direction"] == "yes":
            # exit_price is YES price; entry_price is YES price paid
            pnl = pos["size"] * ((exit_price - pos["entry_price"]) / 100.0)
            self.bankroll += pos["size"] * (exit_price / 100.0)
        else:
            # entry_price is NO price paid; exit_price is YES price (bankroll uses 100-exit_price)
            current_no_price = 100 - exit_price
            pnl = pos["size"] * ((current_no_price - pos["entry_price"]) / 100.0)
            self.bankroll += pos["size"] * (current_no_price / 100.0)
        self.realized_pnl += pnl
        close_record = {**pos, "exit_price": exit_price, "pnl": pnl, "status": "closed"}
        self._order_log.append(close_record)
        self._persist_log()
        self.logger.info(f"[PAPER] Closed {ticker} @ {exit_price}c P&L=${pnl:.2f}")
        return close_record

    def get_positions(self) -> List[Dict]:
        return list(self._positions.values())

    def get_order_log(self) -> List[Dict]:
        return self._order_log

    def _persist_log(self):
        import tempfile
        data = json.dumps(self._order_log, indent=2).encode()
        fd, tmp_path = tempfile.mkstemp(dir=self.config.data_dir, suffix=".tmp")
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        os.replace(tmp_path, self._log_path)
