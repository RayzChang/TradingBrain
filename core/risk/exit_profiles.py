"""Shared exit profile definitions for each strategy family."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExitProfile:
    """Per-strategy exit plan used across planning and position management."""

    family: str
    stop_loss_atr_mult: float
    tp1_atr_mult: float
    tp2_atr_mult: float
    tp3_atr_mult: float
    min_risk_reward: float
    tp1_close_pct: float
    tp2_close_pct: float
    tp1_trailing_atr_mult: float
    tp2_trailing_atr_mult: float
    tp2_final_exit: bool = False


def normalize_strategy_family(strategy_name: str) -> str:
    """Map concrete strategy names to their shared exit profile family."""
    name = (strategy_name or "").strip().lower()
    if name in {"breakout", "breakout_retest"}:
        return "breakout"
    if name == "trend_following":
        return "trend_following"
    if name == "mean_reversion":
        return "mean_reversion"
    return "default"


DEFAULT_EXIT_PROFILES: dict[str, ExitProfile] = {
    "default": ExitProfile(
        family="default",
        stop_loss_atr_mult=1.5,
        tp1_atr_mult=2.0,
        tp2_atr_mult=3.0,
        tp3_atr_mult=4.5,
        min_risk_reward=1.5,
        tp1_close_pct=0.30,
        tp2_close_pct=0.30,
        tp1_trailing_atr_mult=1.5,
        tp2_trailing_atr_mult=1.0,
    ),
    "trend_following": ExitProfile(
        family="trend_following",
        stop_loss_atr_mult=1.5,
        tp1_atr_mult=2.0,
        tp2_atr_mult=3.5,
        tp3_atr_mult=5.0,
        min_risk_reward=1.6,
        tp1_close_pct=0.25,
        tp2_close_pct=0.25,
        tp1_trailing_atr_mult=1.8,
        tp2_trailing_atr_mult=1.2,
    ),
    "breakout": ExitProfile(
        family="breakout",
        stop_loss_atr_mult=2.0,
        tp1_atr_mult=1.5,
        tp2_atr_mult=3.0,
        tp3_atr_mult=4.5,
        min_risk_reward=1.4,
        tp1_close_pct=0.40,
        tp2_close_pct=0.35,
        tp1_trailing_atr_mult=1.2,
        tp2_trailing_atr_mult=0.8,
    ),
    "mean_reversion": ExitProfile(
        family="mean_reversion",
        stop_loss_atr_mult=1.25,
        tp1_atr_mult=1.0,
        tp2_atr_mult=1.8,
        tp3_atr_mult=0.0,
        min_risk_reward=0.8,
        tp1_close_pct=0.75,
        tp2_close_pct=0.25,
        tp1_trailing_atr_mult=0.0,
        tp2_trailing_atr_mult=0.0,
        tp2_final_exit=True,
    ),
}


def get_exit_profile(strategy_name: str) -> ExitProfile:
    """Return the default exit profile for the strategy family."""
    family = normalize_strategy_family(strategy_name)
    return DEFAULT_EXIT_PROFILES[family]
