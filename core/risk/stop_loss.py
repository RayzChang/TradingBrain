"""
Structure-first stop-loss and take-profit calculation.

SL/TP 以技術圖結構（swing high/low、fibonacci）為主，ATR 只在無結構時作為後備。
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
import pandas as pd

from core.risk.exit_profiles import get_exit_profile, normalize_strategy_family
from core.risk.structure_levels import (
    _hard_stop_buffer,
    compute_structure_levels,
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

        # ── SL：結構做主，不混合 ATR ──
        structure_floor_triggered = False
        if structure_stop is not None:
            soft_stop_loss = structure_stop
            hard_stop_loss = structure_hard_stop or structure_stop

            # 入場 K 線止損：和結構取較寬的（保護用）
            if candle_stop is not None:
                if direction == "LONG":
                    soft_stop_loss = min(soft_stop_loss, candle_stop)
                else:
                    soft_stop_loss = max(soft_stop_loss, candle_stop)

            # 安全繩：結構止損太近 → 拒絕開單，不混合
            min_sl_pct = 0.003  # 0.3% of entry
            sl_dist = abs(entry_price - soft_stop_loss)
            if sl_dist < entry_price * min_sl_pct:
                logger.warning(
                    f"STRUCTURE_SL_TOO_CLOSE: {symbol or 'UNKNOWN'} "
                    f"distance={sl_dist:.4f} < {entry_price * min_sl_pct:.4f} "
                    f"(0.3%), rejecting trade"
                )
                return StopLossResult(
                    stop_loss=0.0, soft_stop_loss=0.0, hard_stop_loss=0.0,
                    take_profit=0.0, rejected=True,
                    reason="structure stop too close to entry (<0.3%)",
                )

            # hard_stop buffer 重新計算（確保 hard > soft）
            hs_buffer = abs(float(hard_stop_loss) - float(soft_stop_loss))
            if hs_buffer <= 0:
                hs_buffer = _hard_stop_buffer(entry_price, atr, family)
            if direction == "LONG":
                hard_stop_loss = max(soft_stop_loss - hs_buffer, 0.0)
            else:
                hard_stop_loss = soft_stop_loss + hs_buffer

            logger.info(
                f"STRUCTURE_SL: {symbol or 'UNKNOWN'} "
                f"anchor={f'{structure_stop_anchor:.4f}' if structure_stop_anchor else 'n/a'} "
                f"soft={soft_stop_loss:.4f} hard={hard_stop_loss:.4f} "
                f"distance={sl_dist/entry_price*100:.2f}%"
            )
        else:
            # 無結構 → ATR 作為後備
            if candle_stop is not None:
                if direction == "LONG":
                    soft_stop_loss = min(soft_stop_loss, candle_stop)
                else:
                    soft_stop_loss = max(soft_stop_loss, candle_stop)
            logger.debug(
                f"NO_STRUCTURE_SL: {symbol or 'UNKNOWN'} using ATR fallback "
                f"soft={soft_stop_loss:.4f}"
            )

        # ── TP：結構做主，ATR 只是後備 ──
        # 有結構 TP → 直接用；沒有 → 保留 ATR fallback
        if structure_tp1 is not None:
            tp1 = structure_tp1
        if structure_tp2 is not None:
            tp2 = structure_tp2
        if is_mean_reversion:
            tp3 = 0.0
        elif structure_tp3 is not None:
            tp3 = structure_tp3

        # TP 手續費安全網（只保證不虧手續費，不設人為高地板）
        fee_floor_pct = 0.0025  # 0.25% — 覆蓋來回手續費 0.08% 的 ~3 倍
        if direction == "LONG":
            tp1 = max(tp1, entry_price * (1 + fee_floor_pct))
            tp2 = max(tp2, entry_price * (1 + fee_floor_pct * 2))
            if tp3 > 0:
                tp3 = max(tp3, entry_price * (1 + fee_floor_pct * 3))
        else:
            tp1 = min(tp1, entry_price * (1 - fee_floor_pct))
            tp2 = min(tp2, entry_price * (1 - fee_floor_pct * 2))
            if tp3 > 0:
                tp3 = min(tp3, entry_price * (1 - fee_floor_pct * 3))

        # ── R:R 檢查：用 TP1/SL，不是 TP3/SL ──
        sl_distance_abs = abs(entry_price - soft_stop_loss)
        tp1_distance_abs = abs(tp1 - entry_price)
        if sl_distance_abs <= 0:
            return StopLossResult(
                stop_loss=0.0, soft_stop_loss=0.0, hard_stop_loss=0.0,
                take_profit=0.0, rejected=True,
                reason="invalid structure stop distance",
            )

        tp1_rr = tp1_distance_abs / sl_distance_abs
        if tp1_rr < min_rr:
            logger.warning(
                f"TP1_RR_REJECT: {symbol or 'UNKNOWN'} "
                f"TP1/SL={tp1_rr:.2f} < min_rr={min_rr} "
                f"(TP1_dist={tp1_distance_abs:.4f} SL_dist={sl_distance_abs:.4f})"
            )
            return StopLossResult(
                stop_loss=soft_stop_loss,
                soft_stop_loss=soft_stop_loss,
                hard_stop_loss=hard_stop_loss,
                take_profit=tp1,
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
                reason=f"TP1 risk reward {tp1_rr:.2f} below {min_rr}",
            )

        final_target_price = tp2 if is_mean_reversion else tp3

        logger.info(
            f"SL_TP_FINAL: {symbol or 'UNKNOWN'} {direction} "
            f"SL={soft_stop_loss:.4f} TP1={tp1:.4f} TP2={tp2:.4f} "
            f"TP1_RR={tp1_rr:.2f}"
        )

        return StopLossResult(
            stop_loss=round(soft_stop_loss, 4),
            soft_stop_loss=round(soft_stop_loss, 4),
            hard_stop_loss=round(hard_stop_loss, 4),
            take_profit=round(final_target_price, 4) if final_target_price else round(tp1, 4),
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
