"""Position sizing with fixed-margin model and per-coin max leverage (V8)."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from core.risk.exit_profiles import normalize_strategy_family

if TYPE_CHECKING:
    from database.db_manager import DatabaseManager


# Per-coin max leverage fallback table (Binance Futures approximations).
# Used when the exchange API is unavailable (paper mode).
COIN_MAX_LEVERAGE: dict[str, int] = {
    "BTCUSDT": 125, "ETHUSDT": 100, "BNBUSDT": 75,
    "SOLUSDT": 75, "XRPUSDT": 75, "ADAUSDT": 75,
    "DOGEUSDT": 75, "AVAXUSDT": 50, "DOTUSDT": 50,
    "LINKUSDT": 75, "MATICUSDT": 50, "NEARUSDT": 50,
    "ARBUSDT": 50, "OPUSDT": 50, "APTUSDT": 50,
    "SUIUSDT": 50, "ATOMUSDT": 20, "FILUSDT": 50,
    "LTCUSDT": 75, "UNIUSDT": 50,
}


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
    margin_usdt: float = 0.0
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
    """Map signal strength to conviction tier and margin multiplier."""
    s = max(0.0, float(signal_strength))
    if s >= 0.7:
        bonus = min((s - 0.7) * 1.0, 0.3)
        return "A", 1.0 + bonus
    if s >= 0.5:
        return "B", 0.5 + (s - 0.5) * 2.5
    return "C", max(0.25, s * 0.83)


def _daily_pnl_modifier(
    daily_pnl: float,
    balance: float,
    params: dict,
) -> float:
    """Return a 0-1 multiplier that modulates risk based on daily rhythm.

    V8: Thresholds raised significantly to match $50-200U/day profit target.
    """
    del params

    modifier = 1.0

    profit_lock_threshold = balance * 0.03
    profit_close_threshold = balance * 0.05
    profit_stop_threshold = balance * 0.08
    drawdown_reduce_threshold = balance * 0.02
    drawdown_focus_threshold = balance * 0.04
    drawdown_stop_threshold = balance * 0.06

    if daily_pnl >= profit_stop_threshold:
        logger.debug(
            f"Daily P&L modifier: profit {daily_pnl:.1f}U reached "
            f"{profit_stop_threshold:.1f}U hard-stop threshold -> risk x0.0"
        )
        return 0.0
    if daily_pnl >= profit_close_threshold:
        modifier *= 0.4
        logger.debug(
            f"Daily P&L modifier: profit {daily_pnl:.1f}U reached "
            f"{profit_close_threshold:.1f}U near-close threshold -> risk x0.4"
        )
    elif daily_pnl >= profit_lock_threshold:
        modifier *= 0.7
        logger.debug(
            f"Daily P&L modifier: profit {daily_pnl:.1f}U reached "
            f"{profit_lock_threshold:.1f}U protect-gains threshold -> risk x0.7"
        )

    loss = abs(daily_pnl) if daily_pnl < 0 else 0.0
    if loss >= drawdown_stop_threshold:
        logger.debug(
            f"Daily P&L modifier: loss {daily_pnl:.1f}U reached "
            f"{drawdown_stop_threshold:.1f}U hard-stop threshold -> risk x0.0"
        )
        return 0.0
    if loss >= drawdown_focus_threshold:
        modifier *= 0.3
        logger.debug(
            f"Daily P&L modifier: loss {daily_pnl:.1f}U reached "
            f"{drawdown_focus_threshold:.1f}U focus-only threshold -> risk x0.3"
        )
    elif loss >= drawdown_reduce_threshold:
        modifier *= 0.6
        logger.debug(
            f"Daily P&L modifier: loss {daily_pnl:.1f}U reached "
            f"{drawdown_reduce_threshold:.1f}U reduce-risk threshold -> risk x0.6"
        )

    return modifier


def get_coin_max_leverage(symbol: str) -> int:
    """Return the estimated max leverage for a symbol from the fallback table."""
    return COIN_MAX_LEVERAGE.get(symbol, 20)


class PositionSizer:
    """
    Fixed-margin position sizing with per-coin max leverage (V8).

    Sizing model:
    1. Determine margin per trade based on coin's max leverage tier.
    2. Apply conviction and daily PnL modifiers to the margin.
    3. Notional = margin * leverage.
    4. Full account balance acts as collateral (CROSSED mode).
    """

    # Default margin range (USDT) - adjustable via risk params.
    DEFAULT_MARGIN_LOW = 100    # For high-leverage coins (>=75x)
    DEFAULT_MARGIN_HIGH = 500   # For low-leverage coins (<=25x)

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

    def _compute_margin(
        self,
        coin_max_leverage: int,
        margin_low: float,
        margin_high: float,
    ) -> float:
        """Compute margin per trade based on coin's max leverage tier.

        High-leverage coins (BTC 125x) → lower margin ($100-200).
        Low-leverage coins (ATOM 20x) → higher margin ($400-500).
        Linear interpolation between the two extremes.
        """
        if coin_max_leverage >= 75:
            return margin_low
        if coin_max_leverage <= 25:
            return margin_high
        # Linear interpolation: 75x→margin_low, 25x→margin_high
        ratio = (coin_max_leverage - 25) / (75 - 25)
        return margin_high - ratio * (margin_high - margin_low)

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
        coin_max_leverage: int | None = None,
    ) -> PositionSizeResult:
        """
        Compute the allowed position size in USDT using fixed-margin model.

        V8: Position = margin * leverage, where leverage is the coin's max.
        Full account balance acts as collateral in CROSSED mode.
        """
        del direction, stop_loss_atr_mult

        params = self._get_params()
        min_notional = float(params.get("min_notional_value", 10))

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

        # Determine coin's max leverage
        if coin_max_leverage is None:
            from config.settings import DEFAULT_LEVERAGE
            coin_max_leverage = int(params.get("max_leverage", DEFAULT_LEVERAGE))

        # Compute base margin based on leverage tier
        margin_low = float(params.get("fixed_margin_low", self.DEFAULT_MARGIN_LOW))
        margin_high = float(params.get("fixed_margin_high", self.DEFAULT_MARGIN_HIGH))
        base_margin = self._compute_margin(coin_max_leverage, margin_low, margin_high)

        # Apply conviction multiplier
        raw_strength = float(signal_strength) if signal_strength is not None else 0.5
        tier, conviction_mult = _conviction_tier(raw_strength)
        strategy_weight = self._strategy_risk_weight(strategy_name)
        pnl_mod = _daily_pnl_modifier(daily_pnl, balance, params)

        # Effective margin = base_margin * conviction * strategy_weight * pnl_mod
        effective_margin = base_margin * conviction_mult * strategy_weight * pnl_mod

        # Ensure margin doesn't exceed a safe portion of balance
        max_open = self.max_open_positions(balance)
        max_margin_per_trade = (balance / max_open) * 0.90
        if effective_margin > max_margin_per_trade:
            effective_margin = max_margin_per_trade

        # Notional = margin * leverage
        leverage = coin_max_leverage
        size_usdt = effective_margin * leverage

        effective_risk_pct = effective_margin / balance if balance > 0 else 0.0

        if size_usdt < min_notional:
            logger.warning(
                f"Position size {size_usdt:.2f} USDT < min notional {min_notional}, reject"
            )
            return PositionSizeResult(
                size_usdt=0.0,
                leverage=1,
                rejected=True,
                effective_risk_pct=effective_risk_pct,
                strategy_risk_weight=strategy_weight,
                strength_multiplier=conviction_mult,
                conviction_tier=tier,
                daily_pnl_modifier=pnl_mod,
                margin_usdt=effective_margin,
                reason=f"position size {size_usdt:.2f} < min notional {min_notional} USDT",
            )

        logger.info(
            f"Position sized (V8): tier={tier} conviction={conviction_mult:.2f} "
            f"weight={strategy_weight} pnl_mod={pnl_mod:.2f} "
            f"margin={effective_margin:.1f}U leverage={leverage}x "
            f"notional={size_usdt:.0f}U"
        )
        return PositionSizeResult(
            size_usdt=round(size_usdt, 2),
            leverage=leverage,
            rejected=False,
            effective_risk_pct=round(effective_risk_pct, 6),
            strategy_risk_weight=strategy_weight,
            strength_multiplier=conviction_mult,
            conviction_tier=tier,
            daily_pnl_modifier=pnl_mod,
            margin_usdt=round(effective_margin, 2),
        )

    def max_open_positions(self, balance: float) -> int:
        """Return max simultaneous positions for the current balance."""
        params = self._get_params()
        return _parse_max_open_positions(params.get("max_open_positions", "auto"), balance)
