"""
資金費率監控模組

定時從幣安獲取 USDT 永續合約的資金費率。
資金費率是「否決權」模型的核心數據源之一：
- 正費率過高 (>0.1%) = 多頭過度擁擠 → 否決做多
- 負費率極端 (<-0.1%) = 空頭過度擁擠 → 否決做空
"""

from typing import Optional

import httpx
from loguru import logger

from config.settings import BINANCE_REST_URL
from core.rate_limiter import RateLimiter
from database.db_manager import DatabaseManager


class FundingRateMonitor:
    """幣安合約資金費率監控"""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self.limiter = RateLimiter.get_instance()
        self.base_url = BINANCE_REST_URL
        self._client: Optional[httpx.AsyncClient] = None

        # 記憶體快取：最新資金費率
        self.latest_rates: dict[str, dict] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_funding_rates(self) -> list[dict]:
        """
        獲取所有交易對的最新資金費率。
        API Weight: 1
        """
        await self.limiter.acquire(weight=1)
        client = await self._get_client()

        try:
            response = await client.get(
                f"{self.base_url}/fapi/v1/premiumIndex"
            )
            self.limiter.update_from_headers(dict(response.headers))
            response.raise_for_status()
            data = response.json()

            rates = []
            for item in data:
                rate_info = {
                    "symbol": item["symbol"],
                    "funding_rate": float(item.get("lastFundingRate", 0)),
                    "mark_price": float(item.get("markPrice", 0)),
                    "index_price": float(item.get("indexPrice", 0)),
                    "next_funding_time": int(item.get("nextFundingTime", 0)),
                }
                rates.append(rate_info)
                self.latest_rates[item["symbol"]] = rate_info

            logger.info(f"Funding rates updated: {len(rates)} pairs")
            return rates

        except Exception as e:
            logger.error(f"Failed to fetch funding rates: {e}")
            return []

    async def fetch_and_store(self) -> None:
        """獲取資金費率並存入資料庫"""
        rates = await self.fetch_funding_rates()
        if rates:
            self.db.save_market_info(
                info_type="funding_rate",
                data=rates,
            )

    def get_rate(self, symbol: str) -> Optional[float]:
        """取得指定交易對的最新資金費率"""
        info = self.latest_rates.get(symbol)
        return info["funding_rate"] if info else None

    def get_extreme_rates(
        self, threshold_high: float = 0.001, threshold_low: float = -0.001
    ) -> dict[str, list[dict]]:
        """
        找出資金費率極端的交易對。

        Returns:
            {"high": [極度正費率], "low": [極度負費率]}
        """
        high = []
        low = []
        for symbol, info in self.latest_rates.items():
            rate = info["funding_rate"]
            if rate >= threshold_high:
                high.append(info)
            elif rate <= threshold_low:
                low.append(info)

        if high:
            logger.debug(f"Extreme positive funding: {len(high)} pairs")
        if low:
            logger.debug(f"Extreme negative funding: {len(low)} pairs")

        return {"high": high, "low": low}
