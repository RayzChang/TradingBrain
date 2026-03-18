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
from core.risk.structure_levels import compute_structure_levels, get_structure_stop_floor_mult

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager


@dataclass
class StopLossResult:
    """Calculated exit levels for a trade."""

    stop_loss: float
    take_profit: float
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
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
        structure_tp1 = None
        structure_tp2 = None
        structure_tp3 = None
        if structure_df is not None and not structure_df.empty:
            structure = compute_structure_levels(
                structure_df,
                entry_price,
                direction,
                strategy_name=strategy_name,
            )
            structure_stop = structure.stop_loss
            structure_tp1 = structure.tp1
            structure_tp2 = structure.tp2
            structure_tp3 = structure.tp3

        sl_distance = sl_mult * atr
        tp1_distance = tp1_mult * atr
        tp2_distance = tp2_mult * atr
        tp3_distance = tp3_mult * atr

        if direction == "LONG":
            stop_loss = entry_price - sl_distance
            tp1 = entry_price + tp1_distance
            tp2 = entry_price + tp2_distance
            tp3 = entry_price + tp3_distance if tp3_distance > 0 else 0.0
        else:
            stop_loss = entry_price + sl_distance
            tp1 = entry_price - tp1_distance
            tp2 = entry_price - tp2_distance
            tp3 = entry_price - tp3_distance if tp3_distance > 0 else 0.0

        if structure_stop is not None:
            min_atr_mult = get_structure_stop_floor_mult(strategy_name)
            final_structure_stop = structure_stop
            structure_floor_triggered = False
            if min_atr_mult is not None:
                atr_floor_stop = (
                    entry_price - (min_atr_mult * atr)
                    if direction == "LONG"
                    else entry_price + (min_atr_mult * atr)
                )
                if direction == "LONG":
                    final_structure_stop = min(structure_stop, atr_floor_stop)
                else:
                    final_structure_stop = max(structure_stop, atr_floor_stop)
                if final_structure_stop != structure_stop:
                    structure_floor_triggered = True
                    logger.info(
                        "STRUCTURE_STOP_FLOOR: "
                        f"{symbol or 'UNKNOWN'} structure={structure_stop:.4f} "
                        f"atr_floor={atr_floor_stop:.4f} final={final_structure_stop:.4f}"
                    )
            stop_loss = final_structure_stop
        else:
            structure_floor_triggered = False
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

        final_target_distance = abs((tp2 if is_mean_reversion else tp3) - entry_price)
        final_target_price = tp2 if is_mean_reversion else tp3

        sl_distance_abs = abs(entry_price - stop_loss)
        if sl_distance_abs <= 0:
            return StopLossResult(
                stop_loss=0.0,
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
                stop_loss=stop_loss,
                take_profit=final_target_price,
                tp1=tp1,
                tp2=tp2,
                tp3=tp3,
                sl_atr_mult=sl_mult,
                structure_stop_floor_triggered=structure_floor_triggered,
                rejected=True,
                reason=f"risk reward below {min_rr}",
            )

        return StopLossResult(
            stop_loss=round(stop_loss, 4),
            take_profit=round(final_target_price, 4),
            tp1=round(tp1, 4),
            tp2=round(tp2, 4),
            tp3=round(tp3, 4),
            sl_atr_mult=sl_mult,
            structure_stop_floor_triggered=structure_floor_triggered,
            rejected=False,
        )
