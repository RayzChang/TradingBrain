"""
止損 / 止盈計算 (ATR 動態)

依 ATR 倍數計算止損價與止盈價，並檢查最低風報比。
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager


@dataclass
class StopLossResult:
    """止損止盈結果"""
    stop_loss: float
    take_profit: float
    rejected: bool
    reason: str = ""


class StopLossCalculator:
    """
    ATR 動態止損止盈。
    LONG: 止損在下方，止盈在上方
    SHORT: 止損在上方，止盈在下方
    """

    def __init__(self, db: "DatabaseManager | None" = None) -> None:
        self.db = db

    def _get_params(self) -> dict:
        if self.db is None:
            return {}
        return self.db.get_risk_params()

    def compute(
        self,
        entry_price: float,
        atr: float,
        direction: str,
        stop_loss_atr_mult: float | None = None,
        take_profit_atr_mult: float | None = None,
        min_risk_reward: float | None = None,
    ) -> StopLossResult:
        """
        計算止損價與止盈價。

        Args:
            entry_price: 進場價
            atr: 當前 ATR
            direction: "LONG" | "SHORT"
            stop_loss_atr_mult: 止損 ATR 倍數
            take_profit_atr_mult: 止盈 ATR 倍數
            min_risk_reward: 最低風報比（盈虧比），不滿足則 rejected=True

        Returns:
            StopLossResult
        """
        params = self._get_params()
        sl_mult = stop_loss_atr_mult if stop_loss_atr_mult is not None else float(
            params.get("stop_loss_atr_mult", 1.5)
        )
        tp_mult = take_profit_atr_mult if take_profit_atr_mult is not None else float(
            params.get("take_profit_atr_mult", 2.25)
        )
        min_rr = min_risk_reward if min_risk_reward is not None else float(
            params.get("min_risk_reward", 1.5)
        )

        if entry_price <= 0 or atr <= 0:
            return StopLossResult(
                stop_loss=0.0, take_profit=0.0, rejected=True, reason="entry/atr 無效"
            )

        sl_distance = sl_mult * atr
        tp_distance = tp_mult * atr

        if direction == "LONG":
            stop_loss = entry_price - sl_distance
            take_profit = entry_price + tp_distance
        else:
            stop_loss = entry_price + sl_distance
            take_profit = entry_price - tp_distance

        # 風報比：盈利距離 / 虧損距離 >= min_risk_reward
        if tp_distance / sl_distance < min_rr:
            logger.warning(
                f"TP/SL ratio {tp_distance/sl_distance:.2f} < min_risk_reward {min_rr}, reject"
            )
            return StopLossResult(
                stop_loss=stop_loss,
                take_profit=take_profit,
                rejected=True,
                reason=f"風報比不足 {min_rr}",
            )

        return StopLossResult(
            stop_loss=round(stop_loss, 4),
            take_profit=round(take_profit, 4),
            rejected=False,
        )
