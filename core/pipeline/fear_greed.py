"""
恐懼與貪婪指數監控模組

使用 Alternative.me 免費 API 獲取加密貨幣恐懼貪婪指數。
此為「否決權」模型的數據源之一：
- 指數 > 80 (極度貪婪) → 否決做多信號
- 指數 < 20 (極度恐懼) → 否決做空信號
"""

from typing import Optional

import httpx
from loguru import logger

from database.db_manager import DatabaseManager

FEAR_GREED_API = "https://api.alternative.me/fng/"


class FearGreedMonitor:
    """加密貨幣恐懼與貪婪指數監控"""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self._client: Optional[httpx.AsyncClient] = None

        # 記憶體快取
        self.latest_value: Optional[int] = None
        self.latest_classification: Optional[str] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_index(self) -> Optional[dict]:
        """
        獲取最新恐懼貪婪指數。

        Returns:
            {"value": 72, "classification": "Greed", "timestamp": "..."}
        """
        client = await self._get_client()

        try:
            response = await client.get(FEAR_GREED_API, params={"limit": 1})
            response.raise_for_status()
            data = response.json()

            if "data" not in data or not data["data"]:
                logger.warning("Fear & Greed API returned empty data")
                return None

            entry = data["data"][0]
            result = {
                "value": int(entry["value"]),
                "classification": entry["value_classification"],
                "timestamp": entry["timestamp"],
            }

            self.latest_value = result["value"]
            self.latest_classification = result["classification"]

            logger.info(
                f"Fear & Greed Index: {result['value']} ({result['classification']})"
            )
            return result

        except Exception as e:
            logger.error(f"Failed to fetch Fear & Greed Index: {e}")
            return None

    async def fetch_and_store(self) -> None:
        """獲取恐懼貪婪指數並存入資料庫"""
        result = await self.fetch_index()
        if result:
            self.db.save_market_info(
                info_type="fear_greed",
                data=result,
            )

    def get_value(self) -> Optional[int]:
        """取得最新指數值 (0-100)"""
        return self.latest_value

    def is_extreme_greed(self, threshold: int = 80) -> bool:
        """是否處於極度貪婪"""
        return self.latest_value is not None and self.latest_value >= threshold

    def is_extreme_fear(self, threshold: int = 20) -> bool:
        """是否處於極度恐懼"""
        return self.latest_value is not None and self.latest_value <= threshold
