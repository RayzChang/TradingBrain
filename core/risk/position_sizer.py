"""
倉位計算器 (Position Sizer)

依每筆風險比例與 ATR 計算名義倉位，並強制最小下單額保護。
倉位數依資金自適應：<500U=1倉, 500-1000U=2倉, >1000U=3倉。
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager


@dataclass
class PositionSizeResult:
    """倉位計算結果"""
    size_usdt: float
    leverage: int
    rejected: bool
    reason: str = ""


def _parse_max_open_positions(value: str | int, balance: float) -> int:
    """將 max_open_positions 轉為整數（auto 依資金）"""
    if isinstance(value, int) and value >= 1:
        return min(value, 10)
    if value == "auto" or value is None:
        if balance < 500:
            return 1
        if balance < 1000:
            return 2
        return 3
    return 1


class PositionSizer:
    """
    倉位計算 + 最小下單額保護。

    公式: risk_amount = balance * max_risk_per_trade
         stop_distance = atr * stop_loss_atr_mult (由呼叫方傳入或從 params 讀)
         position_size_usdt = risk_amount / (stop_distance_pct of entry)
    簡化: 若以「固定止損%」估算: size = risk_amount / (stop_pct/100)
    此處採用: size_usdt = risk_amount / (atr_mult * atr / entry_price) 即 risk_amount / (止損距離佔價格%)
    """

    def __init__(self, db: "DatabaseManager | None" = None) -> None:
        self.db = db

    def _get_params(self) -> dict:
        if self.db is None:
            return {}
        return self.db.get_risk_params()

    def compute(
        self,
        balance: float,
        entry_price: float,
        atr: float,
        direction: str,
        stop_loss_atr_mult: float | None = None,
    ) -> PositionSizeResult:
        """
        計算建議倉位（名義價值 USDT）。

        Args:
            balance: 當前權益/餘額 (USDT)
            entry_price: 進場價
            atr: 當前 ATR
            direction: "LONG" | "SHORT"
            stop_loss_atr_mult: 止損 ATR 倍數（若不傳則從 DB 讀）

        Returns:
            PositionSizeResult: size_usdt, leverage, rejected, reason
        """
        params = self._get_params()
        max_risk = float(params.get("max_risk_per_trade", 0.02))
        min_notional = float(params.get("min_notional_value", 10))
        # 絕對上限 20x，避免 DB/儀表板誤設導致異常大槓桿
        max_leverage = min(int(params.get("max_leverage", 5)), 20)
        atr_mult = stop_loss_atr_mult if stop_loss_atr_mult is not None else float(
            params.get("stop_loss_atr_mult", 1.5)
        )

        if balance <= 0 or entry_price <= 0 or atr <= 0:
            return PositionSizeResult(
                size_usdt=0.0, leverage=1, rejected=True, reason="balance/price/atr 無效"
            )

        risk_amount = balance * max_risk
        # 止損距離（價格）：atr_mult * atr；佔價格比例 = (atr_mult * atr) / entry_price
        stop_distance_pct = (atr_mult * atr) / entry_price
        if stop_distance_pct <= 0:
            return PositionSizeResult(
                size_usdt=0.0, leverage=1, rejected=True, reason="止損距離為 0"
            )

        # 倉位名義價值 = risk_amount / stop_distance_pct（使止損時虧損約等於 risk_amount）
        size_usdt = risk_amount / stop_distance_pct
        # 防止因為手續費/滑點導致保證金不足，設定 95% 安全緩衝
        # 並根據最大同時持倉數量平分可用保證金
        max_open = self.max_open_positions(balance)
        safe_balance_per_trade = (balance / max_open) * 0.95
        
        # 名義價值上限：可用保證金 * 最大槓桿
        cap_notional = safe_balance_per_trade * max_leverage
        if size_usdt > cap_notional:
            size_usdt = cap_notional
            
        leverage = min(max_leverage, max(1, int(size_usdt / safe_balance_per_trade))) if safe_balance_per_trade > 0 else 1

        if size_usdt < min_notional:
            logger.warning(
                f"Position size {size_usdt:.2f} USDT < min notional {min_notional}, reject"
            )
            return PositionSizeResult(
                size_usdt=0.0,
                leverage=1,
                rejected=True,
                reason=f"倉位 {size_usdt:.2f} < 最小下單額 {min_notional} USDT",
            )

        return PositionSizeResult(
            size_usdt=round(size_usdt, 2),
            leverage=leverage,
            rejected=False,
        )

    def max_open_positions(self, balance: float) -> int:
        """依資金回傳允許的最大同時持倉數"""
        params = self._get_params()
        return _parse_max_open_positions(params.get("max_open_positions", "auto"), balance)
