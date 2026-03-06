from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class MarketSnapshot:
    ticker: str
    timestamp: int
    yes_bid: Optional[int]
    yes_ask: Optional[int]
    no_bid: Optional[int]
    no_ask: Optional[int]
    volume: int
    open_interest: int
    category: str
    title: str = ""
    close_time: str = ""
    settled: Optional[bool] = None  # True=YES won, False=NO won, None=open

    @property
    def mid_price(self) -> Optional[float]:
        if self.yes_bid is not None and self.yes_ask is not None:
            return (self.yes_bid + self.yes_ask) / 2
        return None

    @property
    def spread(self) -> Optional[int]:
        if self.yes_bid is not None and self.yes_ask is not None:
            return self.yes_ask - self.yes_bid
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker, "timestamp": self.timestamp,
            "yes_bid": self.yes_bid, "yes_ask": self.yes_ask,
            "no_bid": self.no_bid, "no_ask": self.no_ask,
            "volume": self.volume, "open_interest": self.open_interest,
            "category": self.category, "title": self.title,
            "close_time": self.close_time, "settled": self.settled,
        }


@dataclass
class ExternalSignals:
    timestamp: int
    economic_releases: List[Dict] = field(default_factory=list)
    news_headlines: List[Dict] = field(default_factory=list)
    poll_data: List[Dict] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Signal:
    ticker: str
    direction: str          # "yes" or "no"
    confidence: float       # 0.0 to 1.0
    size: int               # number of contracts
    strategy_name: str
    reason: str
    timestamp: int = 0
