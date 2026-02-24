"""
爆倉數據監控模組

監控幣安合約的強制清算事件（爆倉）。
大額連環爆倉 = 市場可能出現反轉或極端波動，觸發「否決權」暫停所有開單。

使用幣安 WebSocket forceOrder stream 或 REST API 獲取清算數據。
"""

import asyncio
import json
import time
from collections import deque
from typing import Optional

import httpx
import websockets
from loguru import logger

from config.settings import BINANCE_REST_URL, BINANCE_WS_URL
from core.rate_limiter import RateLimiter
from database.db_manager import DatabaseManager


class LiquidationMonitor:
    """幣安合約爆倉數據監控"""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self.limiter = RateLimiter.get_instance()
        self.base_url = BINANCE_REST_URL
        self._client: Optional[httpx.AsyncClient] = None

        # 最近 30 分鐘的爆倉事件記錄
        self._recent_liquidations: deque[dict] = deque(maxlen=1000)
        self._surge_detected = False
        self._surge_until: float = 0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def fetch_recent_liquidations(self) -> list[dict]:
        """
        從幣安獲取最近的強制清算訂單。
        使用 /fapi/v1/allForceOrders (Weight: 20)
        """
        await self.limiter.acquire(weight=20)
        client = await self._get_client()

        try:
            response = await client.get(
                f"{self.base_url}/fapi/v1/allForceOrders",
                params={"limit": 100},
            )
            self.limiter.update_from_headers(dict(response.headers))
            response.raise_for_status()
            data = response.json()

            liquidations = []
            for item in data:
                liq = {
                    "symbol": item["symbol"],
                    "side": item["side"],
                    "price": float(item["price"]),
                    "quantity": float(item["origQty"]),
                    "notional": float(item["price"]) * float(item["origQty"]),
                    "time": int(item["time"]),
                }
                liquidations.append(liq)
                self._recent_liquidations.append(liq)

            logger.info(f"Liquidations fetched: {len(liquidations)} events")
            return liquidations

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.debug("Liquidation API not available (may require IP whitelist)")
            else:
                logger.error(f"Failed to fetch liquidations: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch liquidations: {e}")
            return []

    async def fetch_and_store(self) -> None:
        """獲取爆倉數據、偵測異常並存入資料庫"""
        liquidations = await self.fetch_recent_liquidations()
        if liquidations:
            self.db.save_market_info(
                info_type="liquidation",
                data=liquidations,
            )
        self._detect_surge()

    def _detect_surge(self) -> None:
        """
        偵測連環爆倉異常。

        判定條件：15 分鐘內爆倉名義值總和 > $10M，
        或爆倉事件數 > 50 筆。
        """
        now = time.time() * 1000
        cutoff = now - (15 * 60 * 1000)  # 15 minutes

        recent = [
            liq for liq in self._recent_liquidations
            if liq["time"] > cutoff
        ]

        total_notional = sum(liq["notional"] for liq in recent)
        event_count = len(recent)

        if total_notional > 10_000_000 or event_count > 50:
            if not self._surge_detected:
                self._surge_detected = True
                self._surge_until = time.time() + 1800  # 暫停 30 分鐘
                logger.warning(
                    f"LIQUIDATION SURGE DETECTED! "
                    f"Events: {event_count}, Total: ${total_notional:,.0f}. "
                    f"Trading paused for 30 minutes."
                )
        elif self._surge_detected and time.time() > self._surge_until:
            self._surge_detected = False
            logger.info("Liquidation surge cooldown ended, trading resumed")

    @property
    def is_surge(self) -> bool:
        """是否正在發生爆倉異常"""
        if self._surge_detected and time.time() > self._surge_until:
            self._surge_detected = False
        return self._surge_detected

    def get_stats(self) -> dict:
        """取得爆倉統計數據（供儀表板）"""
        now = time.time() * 1000
        cutoff_15m = now - (15 * 60 * 1000)
        cutoff_1h = now - (60 * 60 * 1000)

        recent_15m = [l for l in self._recent_liquidations if l["time"] > cutoff_15m]
        recent_1h = [l for l in self._recent_liquidations if l["time"] > cutoff_1h]

        return {
            "events_15m": len(recent_15m),
            "events_1h": len(recent_1h),
            "notional_15m": sum(l["notional"] for l in recent_15m),
            "notional_1h": sum(l["notional"] for l in recent_1h),
            "is_surge": self.is_surge,
            "surge_until": self._surge_until if self._surge_detected else None,
        }
