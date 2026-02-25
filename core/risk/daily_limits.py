"""
每日虧損 / 回撤熔斷 (Daily Limits & Drawdown Guard)

- 今日虧損超過 max_daily_loss * balance → 禁止開新倉
- 當前權益自高水位回撤超過 max_drawdown → 禁止開新倉
高水位 (equity_high_water_mark) 由呼叫方在權益創高時更新至 risk_params。
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager


@dataclass
class DailyLimitsResult:
    """每日熔斷檢查結果"""
    can_open: bool
    reason: str = ""


class DailyLimitsChecker:
    """
    每日虧損上限與最大回撤檢查。
    """

    def __init__(self, db: "DatabaseManager") -> None:
        self.db = db

    def can_open(
        self,
        current_balance: float,
        daily_pnl: float | None = None,
    ) -> DailyLimitsResult:
        """
        檢查是否允許開新倉。

        Args:
            current_balance: 當前權益（用於每日虧損上限與回撤計算）
            daily_pnl: 今日已實現損益；若不傳則從 DB 查

        Returns:
            DailyLimitsResult.can_open, reason
        """
        params = self.db.get_risk_params()
        max_daily_loss = float(params.get("max_daily_loss", 0.05))
        max_drawdown = float(params.get("max_drawdown", 0.15))

        if daily_pnl is None:
            daily_pnl = self.db.get_daily_pnl()

        # 每日虧損熔斷
        loss_limit = current_balance * max_daily_loss
        if daily_pnl < -loss_limit:
            reason = f"今日虧損 {daily_pnl:.2f} 已達上限 {-loss_limit:.2f}"
            logger.warning(f"Daily limit triggered: {reason}")
            return DailyLimitsResult(can_open=False, reason=reason)

        # 回撤熔斷：當前權益 vs 高水位
        hwm = params.get("equity_high_water_mark")
        if hwm is not None:
            try:
                hwm_f = float(hwm)
            except (TypeError, ValueError):
                hwm_f = current_balance
        else:
            hwm_f = current_balance

        if hwm_f <= 0:
            return DailyLimitsResult(can_open=True)

        drawdown = (hwm_f - current_balance) / hwm_f
        if drawdown >= max_drawdown:
            reason = f"回撤 {drawdown:.1%} >= 上限 {max_drawdown:.1%}"
            logger.warning(f"Drawdown limit triggered: {reason}")
            return DailyLimitsResult(can_open=False, reason=reason)

        return DailyLimitsResult(can_open=True)

    def update_high_water_mark(self, current_equity: float) -> None:
        """權益創高時由呼叫方呼叫，更新 equity_high_water_mark"""
        params = self.db.get_risk_params()
        hwm = params.get("equity_high_water_mark")
        try:
            hwm_f = float(hwm) if hwm is not None else 0.0
        except (TypeError, ValueError):
            hwm_f = 0.0
        if current_equity > hwm_f:
            self.db.set_risk_param("equity_high_water_mark", current_equity, changed_by="risk_manager")
