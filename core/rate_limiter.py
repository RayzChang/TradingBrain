"""
全局 API 限流器 (Singleton)

所有幣安 API 請求必須經過此模組，防止觸發交易所的 429 限制。
追蹤每分鐘的 API 權重消耗，接近上限時自動排隊等待。
"""

import asyncio
import time
from collections import deque
from typing import Optional

from loguru import logger

from config.settings import (
    RATE_LIMIT_WEIGHT_PER_MINUTE,
    RATE_LIMIT_ORDER_PER_MINUTE,
    RATE_LIMIT_SAFETY_MARGIN,
)


class RateLimiter:
    """
    幣安 API 限流器 — 單例模式

    用法:
        limiter = RateLimiter.get_instance()
        await limiter.acquire(weight=5)  # 等待直到有足夠的權重配額
        response = await make_api_call()
        limiter.update_from_headers(response.headers)  # 用回應 header 更新實際消耗
    """

    _instance: Optional["RateLimiter"] = None

    def __init__(self) -> None:
        if RateLimiter._instance is not None:
            raise RuntimeError("Use RateLimiter.get_instance()")

        self._max_weight = int(RATE_LIMIT_WEIGHT_PER_MINUTE * RATE_LIMIT_SAFETY_MARGIN)
        self._max_orders = int(RATE_LIMIT_ORDER_PER_MINUTE * RATE_LIMIT_SAFETY_MARGIN)

        # (timestamp, weight) 記錄最近 60 秒內的 API 呼叫
        self._weight_log: deque[tuple[float, int]] = deque()
        self._order_log: deque[float] = deque()

        self._lock = asyncio.Lock()
        logger.info(
            f"RateLimiter initialized: max_weight={self._max_weight}/min, "
            f"max_orders={self._max_orders}/min"
        )

    @classmethod
    def get_instance(cls) -> "RateLimiter":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """重置單例（僅用於測試）"""
        cls._instance = None

    def _cleanup_old_entries(self) -> None:
        """清除超過 60 秒的記錄"""
        cutoff = time.time() - 60.0
        while self._weight_log and self._weight_log[0][0] < cutoff:
            self._weight_log.popleft()
        while self._order_log and self._order_log[0] < cutoff:
            self._order_log.popleft()

    @property
    def current_weight(self) -> int:
        """當前 60 秒內已消耗的權重"""
        self._cleanup_old_entries()
        return sum(w for _, w in self._weight_log)

    @property
    def current_orders(self) -> int:
        """當前 60 秒內已下的訂單數"""
        self._cleanup_old_entries()
        return len(self._order_log)

    @property
    def weight_remaining(self) -> int:
        return max(0, self._max_weight - self.current_weight)

    @property
    def utilization_pct(self) -> float:
        """API 權重使用率 (0.0 ~ 1.0)"""
        if self._max_weight == 0:
            return 1.0
        return self.current_weight / self._max_weight

    async def acquire(self, weight: int = 1, is_order: bool = False) -> None:
        """
        請求 API 配額。如果超出限制則等待直到有空間。

        Args:
            weight: 該請求的 API 權重（不同端點權重不同）
            is_order: 是否為下單請求（有額外的訂單頻率限制）
        """
        async with self._lock:
            while True:
                self._cleanup_old_entries()
                current_w = sum(w for _, w in self._weight_log)

                weight_ok = (current_w + weight) <= self._max_weight
                order_ok = (not is_order) or (len(self._order_log) < self._max_orders)

                if weight_ok and order_ok:
                    now = time.time()
                    self._weight_log.append((now, weight))
                    if is_order:
                        self._order_log.append(now)
                    return

                # 計算需要等待多久：等到最舊的記錄過期
                if not weight_ok and self._weight_log:
                    wait_until = self._weight_log[0][0] + 60.0
                elif is_order and not order_ok and self._order_log:
                    wait_until = self._order_log[0] + 60.0
                else:
                    wait_until = time.time() + 1.0

                sleep_time = max(0.1, wait_until - time.time())
                logger.warning(
                    f"RateLimiter: 接近限制 (weight={current_w}/{self._max_weight}), "
                    f"等待 {sleep_time:.1f}s"
                )
                # 釋放鎖再 sleep，避免阻塞其他請求
                self._lock.release()
                await asyncio.sleep(sleep_time)
                await self._lock.acquire()

    def update_from_headers(self, headers: dict) -> None:
        """
        從幣安回應 header 更新實際權重消耗。
        幣安會返回 X-MBX-USED-WEIGHT-1m 告訴你實際已用的權重。
        """
        used_weight = headers.get("X-MBX-USED-WEIGHT-1m")
        if used_weight is not None:
            try:
                actual = int(used_weight)
                if actual > self._max_weight * 0.9:
                    logger.warning(
                        f"RateLimiter: 幣安回報高權重消耗 {actual}/{self._max_weight}"
                    )
            except ValueError:
                pass

    def get_status(self) -> dict:
        """返回當前限流器狀態（供儀表板顯示）"""
        self._cleanup_old_entries()
        return {
            "weight_used": self.current_weight,
            "weight_max": self._max_weight,
            "weight_remaining": self.weight_remaining,
            "utilization_pct": round(self.utilization_pct * 100, 1),
            "orders_used": self.current_orders,
            "orders_max": self._max_orders,
        }
