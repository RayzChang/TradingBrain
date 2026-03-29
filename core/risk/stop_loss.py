"""
ATR-based stop-loss and take-profit templates.

Most strategies use the default multi-stage TP1 / TP2 / TP3 profile.
`mean_reversion` uses a shorter profile:
- tighter stop
- nearer TP1
- fixed TP2
- no TP3 / no long-tail trailing expectation
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
import pandas as pd

from core.risk.exit_profiles import get_exit_profile, normalize_strategy_family
from core.risk.structure_levels import (
    _hard_stop_buffer,
    compute_structure_levels,
    get_structure_stop_floor_mult,
)

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager


@dataclass
class StopLossResult:
    """Calculated exit levels for a trade."""

    stop_loss: float
    take_profit: float
    soft_stop_loss: float = 0.0
    hard_stop_loss: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    soft_stop_required_closes: int = 0
    stop_zone_low: float = 0.0
    stop_zone_high: float = 0.0
    tp1_zone_low: float = 0.0
    tp1_zone_high: float = 0.0
    tp2_zone_low: float = 0.0
    tp2_zone_high: float = 0.0
    tp3_zone_low: float = 0.0
    tp3_zone_high: float = 0.0
    sl_atr_mult: float = 0.0
    structure_stop_floor_triggered: bool = False
    rejected: bool = False
    reason: str = ""


class StopLossCalculator:
    """Calculate ATR-based stop-loss and take-profit levels."""

    def __init__(self, db: "DatabaseManager | None" = None) -> None:
        self.db = db

    def _get_params(self) -> dict:
        if self.db is None:
            return {}
        return self.db.get_risk_params()

    @staticmethod
    def _param_with_profile_override(
        params: dict,
        family: str,
        key: str,
        default: float,
    ) -> float:
        """Return a strategy-specific risk param when configured, else the provided default."""
        if family != "default":
            override_key = f"{family}_{key}"
            if override_key in params and params[override_key] is not None:
                return float(params[override_key])
            return float(default)
        if key in params and params[key] is not None:
            return float(params[key])
        return float(default)

    def compute(
        self,
        entry_price: float,
        atr: float,
        direction: str,
        symbol: str = "",
        strategy_name: str = "",
        structure_df: pd.DataFrame | None = None,
        stop_loss_atr_mult: float | None = None,
        take_profit_atr_mult: float | None = None,
        min_risk_reward: float | None = None,
        leverage: int | None = None,
        entry_candle: dict | None = None,
    ) -> StopLossResult:
        """Return stop-loss and take-profit levels for the given strategy."""
        params = self._get_params()
        family = normalize_strategy_family(strategy_name)
        profile = get_exit_profile(strategy_name)
        is_mean_reversion = family == "mean_reversion"

        if entry_price <= 0 or atr <= 0:
            return StopLossResult(
                stop_loss=0.0,
                take_profit=0.0,
                rejected=True,
                reason="entry/atr invalid",
            )

        sl_mult = (
            stop_loss_atr_mult
            if stop_loss_atr_mult is not None
            else self._param_with_profile_override(
                params,
                family,
                "stop_loss_atr_mult",
                profile.stop_loss_atr_mult,
            )
        )
        tp1_mult = self._param_with_profile_override(
            params,
            family,
            "tp1_atr_mult",
            profile.tp1_atr_mult,
        )
        tp2_mult = self._param_with_profile_override(
            params,
            family,
            "tp2_atr_mult",
            profile.tp2_atr_mult,
        )
        if is_mean_reversion:
            tp3_mult = 0.0
        else:
            tp3_mult = (
                take_profit_atr_mult
                if take_profit_atr_mult is not None
                else self._param_with_profile_override(
                    params,
                    family,
                    "tp3_atr_mult",
                    self._param_with_profile_override(
                        params,
                        family,
                        "take_profit_atr_mult",
                        profile.tp3_atr_mult,
                    ),
                )
            )
        min_rr = (
            min_risk_reward
            if min_risk_reward is not None
            else self._param_with_profile_override(
                params,
                family,
                "min_risk_reward",
                profile.min_risk_reward,
            )
        )

        structure_stop = None
        structure_hard_stop = None
        structure_stop_anchor = None
        stop_zone_low = None
        stop_zone_high = None
        structure_tp1 = None
        structure_tp1_zone_low = None
        structure_tp1_zone_high = None
        structure_tp2 = None
        structure_tp2_zone_low = None
        structure_tp2_zone_high = None
        structure_tp3 = None
        structure_tp3_zone_low = None
        structure_tp3_zone_high = None
        if structure_df is not None and not structure_df.empty:
            structure = compute_structure_levels(
                structure_df,
                entry_price,
                direction,
                strategy_name=strategy_name,
                atr=atr,
            )
            structure_stop = structure.stop_loss
            structure_hard_stop = structure.hard_stop_loss
            structure_stop_anchor = structure.stop_anchor
            stop_zone_low = structure.stop_zone_low
            stop_zone_high = structure.stop_zone_high
            structure_tp1 = structure.tp1
            structure_tp1_zone_low = structure.tp1_zone_low
            structure_tp1_zone_high = structure.tp1_zone_high
            structure_tp2 = structure.tp2
            structure_tp2_zone_low = structure.tp2_zone_low
            structure_tp2_zone_high = structure.tp2_zone_high
            structure_tp3 = structure.tp3
            structure_tp3_zone_low = structure.tp3_zone_low
            structure_tp3_zone_high = structure.tp3_zone_high

        sl_distance = sl_mult * atr
        tp1_distance = tp1_mult * atr
        tp2_distance = tp2_mult * atr
        tp3_distance = tp3_mult * atr

        if direction == "LONG":
            soft_stop_loss = entry_price - sl_distance
            hard_stop_loss = soft_stop_loss
            tp1 = entry_price + tp1_distance
            tp2 = entry_price + tp2_distance
            tp3 = entry_price + tp3_distance if tp3_distance > 0 else 0.0
        else:
            soft_stop_loss = entry_price + sl_distance
            hard_stop_loss = soft_stop_loss
            tp1 = entry_price - tp1_distance
            tp2 = entry_price - tp2_distance
            tp3 = entry_price - tp3_distance if tp3_distance > 0 else 0.0

        # ── 入場 K 線止損計算 ──
        candle_stop: float | None = None
        if entry_candle is not None:
            ec_low = entry_candle.get("low")
            ec_high = entry_candle.get("high")
            if direction == "LONG" and ec_low is not None and float(ec_low) > 0:
                candle_stop = float(ec_low) * 0.998
            elif direction == "SHORT" and ec_high is not None and float(ec_high) > 0:
                candle_stop = float(ec_high) * 1.002

        if structure_stop is not None:
            soft_stop_loss = structure_stop
            hard_stop_loss = structure_hard_stop or structure_stop
            structure_floor_triggered = bool(
                structure_stop_anchor is not None
                and round(float(structure_stop_anchor), 4) != round(float(structure_stop), 4)
            )

            # 融合 candle_stop：取結構止損和入場 K 線止損中較寬的
            if candle_stop is not None:
                if direction == "LONG":
                    soft_stop_loss = min(soft_stop_loss, candle_stop)
                else:
                    soft_stop_loss = max(soft_stop_loss, candle_stop)

            floor_mult = get_structure_stop_floor_mult(strategy_name)
            if floor_mult is not None and atr > 0:
                min_distance = float(floor_mult) * float(atr)
                actual_distance = abs(entry_price - soft_stop_loss)
                if actual_distance < min_distance:
                    hard_stop_buffer = abs(float(hard_stop_loss) - float(soft_stop_loss))
                    if hard_stop_buffer <= 0:
                        hard_stop_buffer = _hard_stop_buffer(entry_price, atr, family)
                    # 軟化 ATR floor：混合而非硬覆蓋
                    # blended = structure_stop * 0.6 + atr_floor * 0.4
                    if direction == "LONG":
                        atr_floor_stop = entry_price - min_distance
                        blended_stop = soft_stop_loss * 0.6 + atr_floor_stop * 0.4
                        soft_stop_loss = blended_stop
                        hard_stop_loss = max(soft_stop_loss - hard_stop_buffer, 0.0)
                    else:
                        atr_floor_stop = entry_price + min_distance
                        blended_stop = soft_stop_loss * 0.6 + atr_floor_stop * 0.4
                        soft_stop_loss = blended_stop
                        hard_stop_loss = soft_stop_loss + hard_stop_buffer
                    structure_floor_triggered = True
                    logger.info(
                        "STRUCTURE_STOP_FLOOR: "
                        f"{symbol or 'UNKNOWN'} structure={structure_stop:.4f} "
                        f"atr_floor={atr_floor_stop:.4f} blended={soft_stop_loss:.4f}"
                    )

            # 安全下限：candle_stop 不得比 atr_floor * 0.5 更近
            if candle_stop is not None and atr > 0:
                min_safe = 0.5 * atr
                candle_distance = abs(entry_price - candle_stop)
                if candle_distance < min_safe:
                    logger.debug(
                        f"CANDLE_STOP_SAFETY: candle_stop too close "
                        f"({candle_distance:.4f} < {min_safe:.4f}), widening"
                    )

            if structure_floor_triggered:
                anchor_text = (
                    f"{structure_stop_anchor:.4f}"
                    if structure_stop_anchor is not None
                    else "n/a"
                )
                logger.info(
                    "STRUCTURE_STOP_ZONE: "
                    f"{symbol or 'UNKNOWN'} anchor={anchor_text} "
                    f"soft={soft_stop_loss:.4f} hard={hard_stop_loss:.4f}"
                )
        else:
            structure_floor_triggered = False
            # 沒有結構止損時，如果有 candle_stop 就用它
            if candle_stop is not None:
                if direction == "LONG":
                    soft_stop_loss = min(soft_stop_loss, candle_stop)
                else:
                    soft_stop_loss = max(soft_stop_loss, candle_stop)

        if structure_tp1 is not None:
            if direction == "LONG":
                tp1 = max(structure_tp1, tp1)
            else:
                tp1 = min(structure_tp1, tp1)
        if structure_tp2 is not None:
            if direction == "LONG":
                tp2 = max(structure_tp2, tp2)
            else:
                tp2 = min(structure_tp2, tp2)
        if structure_tp3 is not None or is_mean_reversion:
            if is_mean_reversion:
                tp3 = 0.0
            elif structure_tp3 is not None:
                if direction == "LONG":
                    tp3 = max(structure_tp3, tp3)
                else:
                    tp3 = min(structure_tp3, tp3)

        # ── TP 最低百分比地板：手續費感知動態計算 ──
        # Binance taker fee = 0.04% per side → round-trip = 0.08% of notional
        # 但手續費佔保證金的比例 = round_trip_fee_pct * leverage
        # 要讓 TP 價格移動 * leverage > 手續費佔保證金比例
        # 所以 TP 最低價格移動 % = round_trip_fee / safety_margin
        # safety_margin = 我們要求 TP 淨賺至少是手續費的 2.5 倍
        base_fee_pct = 0.0008  # 0.08% round-trip (of notional = of price move)
        eff_leverage = leverage if leverage and leverage > 0 else 20
        # TP 價格移動需覆蓋：來回手續費 × 安全倍數
        # 例：手續費 0.08%，安全倍數 2.5 → TP 至少移動 0.2%
        # 高槓桿時手續費佔保證金比例更大，但 TP 是按價格移動算的
        # 真正的保底：TP% * leverage > fee% * leverage * safety_mult
        # 簡化後：TP% > fee% * safety_mult（手續費是按名義值算的）
        # 但低槓桿時固定地板可能太高反而卡單，所以取 max
        fee_safety_mult = 2.5  # TP 淨利至少覆蓋 2.5 倍手續費
        fee_aware_floor = base_fee_pct * fee_safety_mult  # = 0.2%
        tp1_floor_pct = max(0.008, fee_aware_floor)        # TP1 至少 0.8%
        tp2_floor_pct = max(0.015, fee_aware_floor * 2)    # TP2 至少 1.5%
        tp3_floor_pct = max(0.025, fee_aware_floor * 3)    # TP3 至少 2.5%
        logger.debug(
            f"TP floor: leverage={eff_leverage}x fee_floor={fee_aware_floor:.4f} "
            f"tp1={tp1_floor_pct:.4f} tp2={tp2_floor_pct:.4f} tp3={tp3_floor_pct:.4f}"
        )

        if direction == "LONG":
            tp1 = max(tp1, entry_price * (1 + tp1_floor_pct))
            tp2 = max(tp2, entry_price * (1 + tp2_floor_pct))
            if tp3 > 0:
                tp3 = max(tp3, entry_price * (1 + tp3_floor_pct))
        else:
            tp1 = min(tp1, entry_price * (1 - tp1_floor_pct))
            tp2 = min(tp2, entry_price * (1 - tp2_floor_pct))
            if tp3 > 0:
                tp3 = min(tp3, entry_price * (1 - tp3_floor_pct))

        final_target_distance = abs((tp2 if is_mean_reversion else tp3) - entry_price)
        final_target_price = tp2 if is_mean_reversion else tp3

        sl_distance_abs = abs(entry_price - soft_stop_loss)
        if sl_distance_abs <= 0:
            return StopLossResult(
                stop_loss=0.0,
                soft_stop_loss=0.0,
                hard_stop_loss=0.0,
                take_profit=0.0,
                rejected=True,
                reason="invalid structure stop distance",
            )

        if final_target_distance / sl_distance_abs < min_rr:
            logger.warning(
                f"Target/SL ratio {final_target_distance/sl_distance_abs:.2f} "
                f"< min_risk_reward {min_rr}, reject"
            )
            return StopLossResult(
                stop_loss=soft_stop_loss,
                soft_stop_loss=soft_stop_loss,
                hard_stop_loss=hard_stop_loss,
                take_profit=final_target_price,
                tp1=tp1,
                tp2=tp2,
                tp3=tp3,
                soft_stop_required_closes=self._soft_stop_required_closes(strategy_name),
                stop_zone_low=stop_zone_low or 0.0,
                stop_zone_high=stop_zone_high or 0.0,
                tp1_zone_low=structure_tp1_zone_low or 0.0,
                tp1_zone_high=structure_tp1_zone_high or 0.0,
                tp2_zone_low=structure_tp2_zone_low or 0.0,
                tp2_zone_high=structure_tp2_zone_high or 0.0,
                tp3_zone_low=structure_tp3_zone_low or 0.0,
                tp3_zone_high=structure_tp3_zone_high or 0.0,
                sl_atr_mult=sl_mult,
                structure_stop_floor_triggered=structure_floor_triggered,
                rejected=True,
                reason=f"risk reward below {min_rr}",
            )

        return StopLossResult(
            stop_loss=round(soft_stop_loss, 4),
            soft_stop_loss=round(soft_stop_loss, 4),
            hard_stop_loss=round(hard_stop_loss, 4),
            take_profit=round(final_target_price, 4),
            tp1=round(tp1, 4),
            tp2=round(tp2, 4),
            tp3=round(tp3, 4),
            soft_stop_required_closes=self._soft_stop_required_closes(strategy_name),
            stop_zone_low=round(stop_zone_low or 0.0, 4),
            stop_zone_high=round(stop_zone_high or 0.0, 4),
            tp1_zone_low=round(structure_tp1_zone_low or 0.0, 4),
            tp1_zone_high=round(structure_tp1_zone_high or 0.0, 4),
            tp2_zone_low=round(structure_tp2_zone_low or 0.0, 4),
            tp2_zone_high=round(structure_tp2_zone_high or 0.0, 4),
            tp3_zone_low=round(structure_tp3_zone_low or 0.0, 4),
            tp3_zone_high=round(structure_tp3_zone_high or 0.0, 4),
            sl_atr_mult=sl_mult,
            structure_stop_floor_triggered=structure_floor_triggered,
            rejected=False,
        )

    @staticmethod
    def _soft_stop_required_closes(strategy_name: str) -> int:
        family = normalize_strategy_family(strategy_name)
        if family == "mean_reversion":
            return 1
        return 2
