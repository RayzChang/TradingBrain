"""
風控核心 (Risk Manager)

整合倉位計算、止損止盈、每日熔斷、連虧冷卻。
信號通過否決引擎後進入此層；通過風控後才進入執行層（Phase6+ 實作）。
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

from core.risk.position_sizer import PositionSizer, PositionSizeResult
from core.risk.stop_loss import StopLossCalculator, StopLossResult
from core.risk.daily_limits import DailyLimitsChecker, DailyLimitsResult
from core.risk.cooldown import CooldownChecker, CooldownResult

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager
    from core.strategy.base import TradeSignal


@dataclass
class RiskCheckResult:
    """風控總結果"""
    passed: bool
    size_usdt: float = 0.0
    leverage: int = 1
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reason: str = ""
    details: dict = field(default_factory=dict)


class RiskManager:
    """
    統一風控入口：依序檢查每日熔斷、連虧冷卻、倉位與止損止盈。
    """

    def __init__(self, db: "DatabaseManager") -> None:
        self.db = db
        self.position_sizer = PositionSizer(db)
        self.stop_loss_calc = StopLossCalculator(db)
        self.daily_limits = DailyLimitsChecker(db)
        self.cooldown = CooldownChecker(db)

    def evaluate(
        self,
        signal: "TradeSignal",
        current_balance: float,
        entry_price: float,
        atr: float,
        open_trades_count: int,
    ) -> RiskCheckResult:
        """
        對一筆通過否決的訊號做風控評估。

        Args:
            signal: 交易信號 (LONG/SHORT)
            current_balance: 當前權益
            entry_price: 預估進場價（可用當前價）
            atr: 當前 ATR
            open_trades_count: 當前未平倉數量

        Returns:
            RiskCheckResult: passed, size_usdt, leverage, stop_loss, take_profit, reason
        """
        # 1. 每日熔斷
        daily = self.daily_limits.can_open(current_balance)
        if not daily.can_open:
            return RiskCheckResult(
                passed=False, reason=daily.reason, details={"stage": "daily_limits"}
            )

        # 2. 連虧冷卻
        cool = self.cooldown.can_open()
        if not cool.can_open:
            return RiskCheckResult(
                passed=False, reason=cool.reason, details={"stage": "cooldown"}
            )

        # 3. 持倉數上限
        max_open = self.position_sizer.max_open_positions(current_balance)
        if open_trades_count >= max_open:
            reason = f"已達最大持倉數 {open_trades_count} >= {max_open}"
            return RiskCheckResult(
                passed=False, reason=reason, details={"stage": "max_positions"}
            )

        # 4. 倉位計算（含最小下單額）
        size_result = self.position_sizer.compute(
            balance=current_balance,
            entry_price=entry_price,
            atr=atr,
            direction=signal.signal_type,
        )
        if size_result.rejected:
            return RiskCheckResult(
                passed=False, reason=size_result.reason, details={"stage": "position_sizer"}
            )

        # 5. 止損止盈（含風報比）
        sl_result = self.stop_loss_calc.compute(
            entry_price=entry_price,
            atr=atr,
            direction=signal.signal_type,
        )
        if sl_result.rejected:
            return RiskCheckResult(
                passed=False, reason=sl_result.reason, details={"stage": "stop_loss"}
            )

        logger.info(
            f"Risk PASS: {signal.symbol} {signal.signal_type} "
            f"size={size_result.size_usdt}U leverage={size_result.leverage} "
            f"sl={sl_result.stop_loss} tp={sl_result.take_profit}"
        )
        return RiskCheckResult(
            passed=True,
            size_usdt=size_result.size_usdt,
            leverage=size_result.leverage,
            stop_loss=sl_result.stop_loss,
            take_profit=sl_result.take_profit,
            details={"stage": "passed"},
        )

    def update_equity_high_water_mark(self, current_equity: float) -> None:
        """平倉或定時更新權益後，若創高則更新高水位（供回撤熔斷用）"""
        self.daily_limits.update_high_water_mark(current_equity)
