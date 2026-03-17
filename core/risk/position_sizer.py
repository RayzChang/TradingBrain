"""Position sizing with structure-first stop distance support."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from core.risk.exit_profiles import normalize_strategy_family

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager


@dataclass
class PositionSizeResult:
    """Calculated position size and leverage."""

    size_usdt: float
    leverage: int
    rejected: bool
    effective_risk_pct: float = 0.0
    strategy_risk_weight: float = 1.0
    strength_multiplier: float = 1.0
    reason: str = ""


def get_strategy_risk_weight(strategy_name: str) -> float:
    """Return the sizing risk weight for the strategy family."""
    family = normalize_strategy_family(strategy_name)
    if family == "breakout":
        return 1.0
    if family == "trend_following":
        return 0.8
    if family == "mean_reversion":
        return 0.7
    return 1.0


def _parse_max_open_positions(value: str | int, balance: float) -> int:
    """Resolve configured max open positions, including the ``auto`` mode."""
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
    Size each position from risk budget first, then cap by available balance/leverage.

    Preferred sizing path:
    1. Use the actual stop-loss price distance when available.
    2. Fall back to ATR-based stop distance when structure is unavailable.
    """

    def __init__(self, db: "DatabaseManager | None" = None) -> None:
        self.db = db

    def _get_params(self) -> dict:
        if self.db is None:
            return {}
        return self.db.get_risk_params()

    @staticmethod
    def _strategy_risk_weight(strategy_name: str) -> float:
        """Return the sizing risk weight for the strategy family."""
        return get_strategy_risk_weight(strategy_name)

    def compute(
        self,
        balance: float,
        entry_price: float,
        atr: float,
        direction: str,
        strategy_name: str = "",
        signal_strength: float | None = None,
        stop_loss_atr_mult: float | None = None,
        stop_loss_price: float | None = None,
    ) -> PositionSizeResult:
        """
        Compute the allowed position size in USDT.

        Args:
            balance: Current account balance.
            entry_price: Planned entry price.
            atr: Current ATR value.
            direction: ``LONG`` or ``SHORT``.
            strategy_name: Strategy family used to scale risk.
            signal_strength: Trade signal confidence multiplier, capped at 1.3x.
            stop_loss_atr_mult: ATR multiple used when no stop-loss price is supplied.
            stop_loss_price: Structure-derived stop-loss price. When valid, sizing uses
                its actual distance to entry instead of an ATR template.
        """
        del direction  # Direction is kept in the signature for compatibility and clarity.

        params = self._get_params()
        max_risk = float(params.get("max_risk_per_trade", 0.02))
        min_notional = float(params.get("min_notional_value", 10))

        from config.settings import DEFAULT_LEVERAGE

        max_leverage = min(int(params.get("max_leverage", DEFAULT_LEVERAGE)), 20)
        atr_mult = stop_loss_atr_mult if stop_loss_atr_mult is not None else float(
            params.get("stop_loss_atr_mult", 1.5)
        )

        if balance <= 0 or entry_price <= 0 or atr <= 0:
            return PositionSizeResult(
                size_usdt=0.0,
                leverage=1,
                rejected=True,
                effective_risk_pct=0.0,
                strategy_risk_weight=1.0,
                strength_multiplier=1.0,
                reason="balance/price/atr invalid",
            )

        strategy_weight = self._strategy_risk_weight(strategy_name)
        strength_mult = 1.0
        if signal_strength is not None:
            strength_mult = max(0.0, min(float(signal_strength), 1.3))

        effective_risk = max_risk * strategy_weight * strength_mult
        risk_amount = balance * effective_risk

        stop_distance_pct = 0.0
        if stop_loss_price is not None and stop_loss_price > 0:
            stop_distance_pct = abs(entry_price - stop_loss_price) / entry_price
        if stop_distance_pct <= 0:
            stop_distance_pct = (atr_mult * atr) / entry_price
        if stop_distance_pct <= 0:
            return PositionSizeResult(
                size_usdt=0.0,
                leverage=1,
                rejected=True,
                effective_risk_pct=effective_risk,
                strategy_risk_weight=strategy_weight,
                strength_multiplier=strength_mult,
                reason="stop distance must be positive",
            )

        size_usdt = risk_amount / stop_distance_pct

        max_open = self.max_open_positions(balance)
        safe_balance_per_trade = (balance / max_open) * 0.95

        cap_notional = safe_balance_per_trade * max_leverage
        if size_usdt > cap_notional:
            size_usdt = cap_notional

        leverage = (
            min(max_leverage, max(1, int(size_usdt / safe_balance_per_trade)))
            if safe_balance_per_trade > 0
            else 1
        )

        if size_usdt < min_notional:
            logger.warning(
                f"Position size {size_usdt:.2f} USDT < min notional {min_notional}, reject"
            )
            return PositionSizeResult(
                size_usdt=0.0,
                leverage=1,
                rejected=True,
                effective_risk_pct=effective_risk,
                strategy_risk_weight=strategy_weight,
                strength_multiplier=strength_mult,
                reason=f"position size {size_usdt:.2f} < min notional {min_notional} USDT",
            )

        return PositionSizeResult(
            size_usdt=round(size_usdt, 2),
            leverage=leverage,
            rejected=False,
            effective_risk_pct=round(effective_risk, 6),
            strategy_risk_weight=strategy_weight,
            strength_multiplier=strength_mult,
        )

    def max_open_positions(self, balance: float) -> int:
        """Return max simultaneous positions for the current balance."""
        params = self._get_params()
        return _parse_max_open_positions(params.get("max_open_positions", "auto"), balance)
