"""
Structure-based stop-loss and take-profit helpers.

The goal is to derive exits from nearby market structure first:
- recent swing highs / lows
- Fibonacci retracement / extension levels

ATR remains the fallback when structure is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.analysis.fibonacci import calculate_fibonacci
from core.risk.exit_profiles import normalize_strategy_family


@dataclass
class StructureLevels:
    stop_loss: float | None
    tp1: float | None
    tp2: float | None
    tp3: float | None
    source: str


def get_structure_stop_floor_mult(strategy_name: str) -> float | None:
    """Minimum ATR distance allowed when a structure stop overrides the ATR fallback."""
    family = normalize_strategy_family(strategy_name)
    if family == "breakout":
        return 2.0
    if family == "trend_following":
        return 1.2
    if family == "mean_reversion":
        return 0.8
    return None


def _recent_swing_low(df: pd.DataFrame, lookback: int = 30, order: int = 2) -> float | None:
    if df.empty or "low" not in df.columns:
        return None
    window = df.tail(lookback).reset_index(drop=True)
    lows = window["low"].tolist()
    candidates: list[float] = []
    for idx in range(order, len(lows) - order):
        value = lows[idx]
        if all(value <= lows[idx - step] for step in range(1, order + 1)) and all(
            value <= lows[idx + step] for step in range(1, order + 1)
        ):
            candidates.append(float(value))
    if candidates:
        return candidates[-1]
    value = float(window["low"].iloc[-min(5, len(window)):].min())
    return value if value > 0 else None


def _recent_swing_high(df: pd.DataFrame, lookback: int = 30, order: int = 2) -> float | None:
    if df.empty or "high" not in df.columns:
        return None
    window = df.tail(lookback).reset_index(drop=True)
    highs = window["high"].tolist()
    candidates: list[float] = []
    for idx in range(order, len(highs) - order):
        value = highs[idx]
        if all(value >= highs[idx - step] for step in range(1, order + 1)) and all(
            value >= highs[idx + step] for step in range(1, order + 1)
        ):
            candidates.append(float(value))
    if candidates:
        return candidates[-1]
    value = float(window["high"].iloc[-min(5, len(window)):].max())
    return value if value > 0 else None


def _fib_levels(df: pd.DataFrame) -> list[float]:
    fib = calculate_fibonacci(df, lookback=min(len(df), 100))
    if fib is None:
        return []

    levels = list(fib.retracement.values()) + list(fib.extension.values())
    return sorted({round(float(level), 4) for level in levels if float(level) > 0})


def _pick_levels_above(entry_price: float, levels: list[float], count: int = 3) -> list[float]:
    return [level for level in levels if level > entry_price][:count]


def _pick_levels_below(entry_price: float, levels: list[float], count: int = 3) -> list[float]:
    candidates = [level for level in levels if level < entry_price]
    candidates.sort(reverse=True)
    return candidates[:count]


def compute_structure_levels(
    df: pd.DataFrame,
    entry_price: float,
    direction: str,
    *,
    strategy_name: str = "",
) -> StructureLevels:
    """
    Derive structure-based stop and targets from recent swings + Fibonacci levels.
    """
    fib_levels = _fib_levels(df)
    recent_low = _recent_swing_low(df)
    recent_high = _recent_swing_high(df)

    if direction == "LONG":
        stop_candidates = _pick_levels_below(entry_price, fib_levels, count=2)
        if recent_low is not None and recent_low < entry_price:
            stop_candidates.insert(0, recent_low)
        stop_loss = max(stop_candidates) if stop_candidates else None

        target_candidates = _pick_levels_above(entry_price, fib_levels, count=4)
        if recent_high is not None and recent_high > entry_price:
            target_candidates = sorted({recent_high, *target_candidates})

        tp1 = target_candidates[0] if len(target_candidates) >= 1 else None
        tp2 = target_candidates[1] if len(target_candidates) >= 2 else None
        tp3 = target_candidates[2] if len(target_candidates) >= 3 else None
    else:
        stop_candidates = _pick_levels_above(entry_price, fib_levels, count=2)
        if recent_high is not None and recent_high > entry_price:
            stop_candidates.insert(0, recent_high)
        stop_loss = min(stop_candidates) if stop_candidates else None

        target_candidates = _pick_levels_below(entry_price, fib_levels, count=4)
        if recent_low is not None and recent_low < entry_price:
            target_candidates = sorted({recent_low, *target_candidates}, reverse=True)

        tp1 = target_candidates[0] if len(target_candidates) >= 1 else None
        tp2 = target_candidates[1] if len(target_candidates) >= 2 else None
        tp3 = target_candidates[2] if len(target_candidates) >= 3 else None

    if normalize_strategy_family(strategy_name) == "mean_reversion":
        tp3 = None

    return StructureLevels(
        stop_loss=stop_loss,
        tp1=tp1,
        tp2=tp2,
        tp3=tp3,
        source="structure",
    )
