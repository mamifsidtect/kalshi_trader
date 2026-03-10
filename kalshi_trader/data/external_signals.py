import time
import os
import json
import tempfile
import requests
from typing import List, Dict, Optional
from kalshi_trader.data.models import ExternalSignals
from kalshi_trader.config import KalshiConfig
from kalshi_trader.utils.logger import get_logger


class ExternalSignalCollector:
    FRED_BASE = "https://api.stlouisfed.org/fred"
    METACULUS_BASE = "https://www.metaculus.com/api2"

    def __init__(self, config: KalshiConfig):
        self.config = config
        self.logger = get_logger(__name__, config.log_level)
        self.fred_api_key = os.getenv("FRED_API_KEY", "")
        self.news_api_key = os.getenv("NEWS_API_KEY", "")
        self.metaculus_api_key = os.getenv("METACULUS_API_KEY", "")
        os.makedirs(config.data_dir, exist_ok=True)
        self._cache_path = os.path.join(config.data_dir, "external_signals_cache.json")

    def collect(self) -> ExternalSignals:
        ts = int(time.time())
        releases, news, polls = [], [], []

        try:
            releases = self._fetch_economic_releases()
        except Exception as e:
            self.logger.warning(f"Economic releases fetch failed: {e}")

        try:
            news = self._fetch_news()
        except Exception as e:
            self.logger.warning(f"News fetch failed: {e}")

        try:
            polls = self._fetch_polls()
        except Exception as e:
            self.logger.warning(f"Polls fetch failed: {e}")

        signals = ExternalSignals(
            timestamp=ts,
            economic_releases=releases,
            news_headlines=news,
            poll_data=polls,
        )
        self._cache(signals)
        return signals

    def _fetch_economic_releases(self) -> List[Dict]:
        if not self.fred_api_key:
            return []
        url = f"{self.FRED_BASE}/releases/dates"
        resp = requests.get(url, params={
            "api_key": self.fred_api_key, "file_type": "json",
            "limit": 20, "sort_order": "desc",
        }, timeout=10)
        resp.raise_for_status()
        return resp.json().get("release_dates", [])

    def _fetch_news(self) -> List[Dict]:
        if not self.news_api_key:
            return []
        url = "https://newsapi.org/v2/top-headlines"
        resp = requests.get(url, params={
            "apiKey": self.news_api_key,
            "category": "business", "pageSize": 20,
        }, timeout=10)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        results = []
        for a in articles:
            try:
                results.append({
                    "headline": a.get("title") or "",
                    "source": (a.get("source") or {}).get("name", ""),
                    "published_at": a.get("publishedAt", ""),
                })
            except Exception:
                continue
        return results

    def _fetch_polls(self) -> List[Dict]:
        if not self.metaculus_api_key:
            return []
        url = f"{self.METACULUS_BASE}/questions/"
        resp = requests.get(url, params={
            "status": "open", "order_by": "-activity", "limit": 20,
        }, headers={"Authorization": f"Token {self.metaculus_api_key}"}, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [{"id": q["id"], "title": q["title"],
                 "community_prediction": q.get("community_prediction")}
                for q in results]

    def _cache(self, signals: ExternalSignals):
        data = json.dumps({
            "timestamp": signals.timestamp,
            "economic_releases": signals.economic_releases,
            "news_headlines": signals.news_headlines,
            "poll_data": signals.poll_data,
        }).encode()
        fd, tmp_path = tempfile.mkstemp(dir=self.config.data_dir, suffix=".tmp")
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        os.replace(tmp_path, self._cache_path)

    def load_cached(self) -> Optional[ExternalSignals]:
        if not os.path.exists(self._cache_path):
            return None
        with open(self._cache_path) as f:
            d = json.load(f)
        return ExternalSignals(
            timestamp=d["timestamp"],
            economic_releases=d.get("economic_releases", []),
            news_headlines=d.get("news_headlines", []),
            poll_data=d.get("poll_data", []),
        )
