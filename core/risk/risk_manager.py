"""Central risk manager for trade admission checks."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

from core.risk.cooldown import CooldownChecker
from core.risk.daily_limits import DailyLimitsChecker
from core.risk.position_sizer import PositionSizer, get_strategy_leverage_cap, get_coin_max_leverage
from core.risk.stop_loss import StopLossCalculator

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager
    from core.strategy.base import TradeSignal


@dataclass
class RiskCheckResult:
    """Final result of all risk checks for a candidate trade."""

    passed: bool
    size_usdt: float = 0.0
    leverage: int = 1
    stop_loss: float = 0.0
    soft_stop_loss: float = 0.0
    hard_stop_loss: float = 0.0
    soft_stop_required_closes: int = 0
    stop_zone_low: float = 0.0
    stop_zone_high: float = 0.0
    take_profit: float = 0.0
    tp1: float = 0.0
    tp1_zone_low: float = 0.0
    tp1_zone_high: float = 0.0
    tp2: float = 0.0
    tp2_zone_low: float = 0.0
    tp2_zone_high: float = 0.0
    tp3: float = 0.0
    tp3_zone_low: float = 0.0
    tp3_zone_high: float = 0.0
    atr: float = 0.0
    effective_risk_pct: float = 0.0
    sl_atr_mult: float = 0.0
    structure_stop_floor_triggered: bool = False
    reason: str = ""
    details: dict = field(default_factory=dict)


class RiskManager:
    """Apply admission checks, exit planning, and position sizing in one place."""

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
        coin_max_leverage: int | None = None,
        entry_candle: dict | None = None,
    ) -> RiskCheckResult:
        """Run all pre-trade risk checks and return the executable risk profile."""
        daily_pnl = self.db.get_daily_pnl()
        daily = self.daily_limits.can_open(current_balance, daily_pnl=daily_pnl)
        if not daily.can_open:
            return RiskCheckResult(
                passed=False,
                reason=daily.reason,
                details={"stage": "daily_limits"},
            )

        cool = self.cooldown.can_open()
        if not cool.can_open:
            return RiskCheckResult(
                passed=False,
                reason=cool.reason,
                details={"stage": "cooldown"},
            )

        # 同幣同方向冷卻
        sym_cool = self.cooldown.per_symbol_direction_cooldown(
            signal.symbol, signal.signal_type,
        )
        if not sym_cool.can_open:
            return RiskCheckResult(
                passed=False,
                reason=sym_cool.reason,
                details={"stage": "symbol_direction_cooldown"},
            )

        max_open = self.position_sizer.max_open_positions(current_balance)
        if open_trades_count >= max_open:
            return RiskCheckResult(
                passed=False,
                reason=f"max open positions reached {open_trades_count} >= {max_open}",
                details={"stage": "max_positions"},
            )

        # 預先算出策略槓桿上限，傳給 SL 計算做手續費感知 TP 地板
        _coin_lev = coin_max_leverage or get_coin_max_leverage(signal.symbol)
        effective_leverage = min(_coin_lev, get_strategy_leverage_cap(signal.strategy_name))

        # Exits come first so sizing can use the actual stop-loss distance.
        sl_result = self.stop_loss_calc.compute(
            entry_price=entry_price,
            atr=atr,
            direction=signal.signal_type,
            symbol=signal.symbol,
            strategy_name=signal.strategy_name,
            structure_df=signal.indicators.get("_structure_df"),
            leverage=effective_leverage,
            entry_candle=entry_candle,
        )
        if sl_result.rejected:
            return RiskCheckResult(
                passed=False,
                reason=sl_result.reason,
                details={"stage": "stop_loss"},
            )

        size_result = self.position_sizer.compute(
            balance=current_balance,
            entry_price=entry_price,
            atr=atr,
            direction=signal.signal_type,
            strategy_name=signal.strategy_name,
            signal_strength=signal.strength,
            stop_loss_price=sl_result.stop_loss,
            daily_pnl=daily_pnl,
            coin_max_leverage=coin_max_leverage,
        )
        if size_result.rejected:
            return RiskCheckResult(
                passed=False,
                reason=size_result.reason,
                details={"stage": "position_sizer"},
            )

        logger.info(
            f"Risk PASS: {signal.symbol} {signal.signal_type} "
            f"size={size_result.size_usdt}U leverage={size_result.leverage} "
            f"soft_sl={sl_result.soft_stop_loss} hard_sl={sl_result.hard_stop_loss} "
            f"tp1={sl_result.tp1} tp2={sl_result.tp2} tp3={sl_result.tp3}"
        )
        return RiskCheckResult(
            passed=True,
            size_usdt=size_result.size_usdt,
            leverage=size_result.leverage,
            stop_loss=sl_result.stop_loss,
            soft_stop_loss=sl_result.soft_stop_loss,
            hard_stop_loss=sl_result.hard_stop_loss,
            soft_stop_required_closes=sl_result.soft_stop_required_closes,
            stop_zone_low=sl_result.stop_zone_low,
            stop_zone_high=sl_result.stop_zone_high,
            take_profit=sl_result.take_profit,
            tp1=sl_result.tp1,
            tp1_zone_low=sl_result.tp1_zone_low,
            tp1_zone_high=sl_result.tp1_zone_high,
            tp2=sl_result.tp2,
            tp2_zone_low=sl_result.tp2_zone_low,
            tp2_zone_high=sl_result.tp2_zone_high,
            tp3=sl_result.tp3,
            tp3_zone_low=sl_result.tp3_zone_low,
            tp3_zone_high=sl_result.tp3_zone_high,
            atr=atr,
            effective_risk_pct=size_result.effective_risk_pct,
            sl_atr_mult=sl_result.sl_atr_mult,
            structure_stop_floor_triggered=sl_result.structure_stop_floor_triggered,
            details={"stage": "passed"},
        )

    def update_equity_high_water_mark(self, current_equity: float) -> None:
        """Update the daily high-water mark used by drawdown protection."""
        self.daily_limits.update_high_water_mark(current_equity)
