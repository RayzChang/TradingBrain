"""Position sizing with conviction-based risk and daily rhythm control.

Sizing flow:
1. Signal strength → conviction multiplier (how aggressive this trade is).
2. Strategy risk weight scales the base risk budget.
3. Daily P&L modifier downshifts risk when nearing profit target or in drawdown.
4. Position size = risk_amount / stop_distance (structure-based).
5. Leverage is the RESULT of sizing, not an input.
"""

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
    conviction_tier: str = ""
    daily_pnl_modifier: float = 1.0
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


def _conviction_tier(signal_strength: float) -> tuple[str, float]:
    """Map signal strength to conviction tier and risk multiplier.

    Returns (tier_label, multiplier).

    Tier A (>=0.7): High conviction — full risk budget, MTF aligned, confirmed.
    Tier B (>=0.5): Medium conviction — decent signal, partial alignment.
    Tier C (<0.5):  Low conviction — marginal, explore with small size.
    """
    s = max(0.0, float(signal_strength))
    if s >= 0.7:
        # Within A tier, strong signals get a bonus up to 1.3x
        bonus = min((s - 0.7) * 1.0, 0.3)
        return "A", 1.0 + bonus
    if s >= 0.5:
        return "B", 0.5 + (s - 0.5) * 2.5  # 0.50 → 1.0
    return "C", max(0.25, s * 0.83)  # 0.30 → 0.25, 0.49 → 0.41


def _daily_pnl_modifier(
    daily_pnl: float,
    balance: float,
    params: dict,
) -> float:
    """Return a 0-1 multiplier that downshifts risk based on daily P&L.

    - Near daily profit target (>=80%): × 0.5 (protect gains)
    - In drawdown (>=50% of daily loss limit): × 0.5
    - Deep drawdown (>=80% of daily loss limit): × 0.25
    """
    modifier = 1.0

    daily_profit_target = float(params.get("daily_profit_target", 0))
    max_daily_loss = float(params.get("max_daily_loss", 0.06))

    # Approaching profit target → reduce aggression
    if daily_profit_target > 0 and daily_pnl > 0:
        start_equity = balance - daily_pnl
        if start_equity > 0:
            target_amount = start_equity * daily_profit_target
            if target_amount > 0:
                progress = daily_pnl / target_amount
                if progress >= 0.8:
                    modifier *= 0.5
                    logger.debug(
                        f"Daily P&L modifier: profit {daily_pnl:.1f}U is {progress:.0%} "
                        f"of target → risk ×0.5"
                    )

    # In drawdown → reduce to protect capital
    loss_limit = balance * max_daily_loss
    if loss_limit > 0 and daily_pnl < 0:
        loss_progress = abs(daily_pnl) / loss_limit
        if loss_progress >= 0.8:
            modifier *= 0.25
            logger.debug(
                f"Daily P&L modifier: loss {daily_pnl:.1f}U is {loss_progress:.0%} "
                f"of limit → risk ×0.25"
            )
        elif loss_progress >= 0.5:
            modifier *= 0.5
            logger.debug(
                f"Daily P&L modifier: loss {daily_pnl:.1f}U is {loss_progress:.0%} "
                f"of limit → risk ×0.5"
            )

    return modifier


class PositionSizer:
    """
    Size each position from conviction-based risk budget, with daily rhythm control.

    Sizing priority:
    1. Use the actual stop-loss price distance (structure-based) when available.
    2. Fall back to ATR-based stop distance when structure is unavailable.
    3. Leverage is calculated as a result of size / balance, never a preset input.
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
        daily_pnl: float = 0.0,
    ) -> PositionSizeResult:
        """
        Compute the allowed position size in USDT.

        Leverage is the RESULT of: risk_amount / (stop_distance × balance),
        not a pre-set constant.

        Args:
            balance: Current account balance.
            entry_price: Planned entry price.
            atr: Current ATR value.
            direction: ``LONG`` or ``SHORT``.
            strategy_name: Strategy family used to scale risk.
            signal_strength: Trade signal confidence (0-1+), maps to conviction tier.
            stop_loss_atr_mult: ATR multiple used when no stop-loss price is supplied.
            stop_loss_price: Structure-derived stop-loss price.
            daily_pnl: Today's realized P&L, used for daily rhythm modulation.
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

        # --- Conviction tier from signal strength ---
        raw_strength = float(signal_strength) if signal_strength is not None else 0.5
        tier, conviction_mult = _conviction_tier(raw_strength)

        # --- Strategy risk weight ---
        strategy_weight = self._strategy_risk_weight(strategy_name)

        # --- Daily P&L rhythm modifier ---
        pnl_mod = _daily_pnl_modifier(daily_pnl, balance, params)

        # --- Effective risk = base × conviction × strategy × daily rhythm ---
        effective_risk = max_risk * conviction_mult * strategy_weight * pnl_mod
        risk_amount = balance * effective_risk

        # --- Stop distance from structure or ATR fallback ---
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
                strength_multiplier=conviction_mult,
                conviction_tier=tier,
                daily_pnl_modifier=pnl_mod,
                reason="stop distance must be positive",
            )

        # --- Position size from risk budget / stop distance ---
        size_usdt = risk_amount / stop_distance_pct

        # --- Leverage is a RESULT, capped at max_leverage ---
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
                strength_multiplier=conviction_mult,
                conviction_tier=tier,
                daily_pnl_modifier=pnl_mod,
                reason=f"position size {size_usdt:.2f} < min notional {min_notional} USDT",
            )

        logger.info(
            f"Position sized: tier={tier} conviction={conviction_mult:.2f} "
            f"weight={strategy_weight} pnl_mod={pnl_mod:.2f} "
            f"risk={effective_risk:.4f} ({risk_amount:.1f}U) "
            f"stop_dist={stop_distance_pct:.4f} size={size_usdt:.0f}U lev={leverage}x"
        )
        return PositionSizeResult(
            size_usdt=round(size_usdt, 2),
            leverage=leverage,
            rejected=False,
            effective_risk_pct=round(effective_risk, 6),
            strategy_risk_weight=strategy_weight,
            strength_multiplier=conviction_mult,
            conviction_tier=tier,
            daily_pnl_modifier=pnl_mod,
        )

    def max_open_positions(self, balance: float) -> int:
        """Return max simultaneous positions for the current balance."""
        params = self._get_params()
        return _parse_max_open_positions(params.get("max_open_positions", "auto"), balance)
