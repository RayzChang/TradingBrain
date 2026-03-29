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
    hard_stop_loss: float | None = None
    stop_anchor: float | None = None
    stop_zone_low: float | None = None
    stop_zone_high: float | None = None
    tp1: float | None = None
    tp1_zone_low: float | None = None
    tp1_zone_high: float | None = None
    tp2: float | None = None
    tp2_zone_low: float | None = None
    tp2_zone_high: float | None = None
    tp3: float | None = None
    tp3_zone_low: float | None = None
    tp3_zone_high: float | None = None
    source: str = "structure"


def get_structure_stop_floor_mult(strategy_name: str) -> float | None:
    """Minimum ATR distance allowed when a structure stop overrides the ATR fallback."""
    family = normalize_strategy_family(strategy_name)
    if family == "breakout":
        return 1.5
    if family == "trend_following":
        return 0.8
    if family == "mean_reversion":
        return 0.5
    return None


def _recent_swing_low(df: pd.DataFrame, lookback: int = 192, order: int = 5) -> float | None:
    """Find the most recent swing low with meaningful structure.

    ``lookback=192`` on 15m data covers ~48 hours.
    ``order=5`` requires the bar to be the lowest within 5 bars on each side
    (75-minute wing on 15m). Falls back to order=3 then order=2 if no swing found.
    """
    if df.empty or "low" not in df.columns:
        return None
    window = df.tail(lookback).reset_index(drop=True)
    lows = window["low"].tolist()

    for try_order in (order, 3, 2):
        candidates: list[float] = []
        for idx in range(try_order, len(lows) - try_order):
            value = lows[idx]
            if all(value <= lows[idx - step] for step in range(1, try_order + 1)) and all(
                value <= lows[idx + step] for step in range(1, try_order + 1)
            ):
                candidates.append(float(value))
        if candidates:
            return candidates[-1]

    value = float(window["low"].iloc[-min(20, len(window)):].min())
    return value if value > 0 else None


def _recent_swing_high(df: pd.DataFrame, lookback: int = 192, order: int = 5) -> float | None:
    """Find the most recent swing high with meaningful structure.

    ``lookback=192`` on 15m data covers ~48 hours.
    ``order=5`` requires the bar to be the highest within 5 bars on each side.
    Falls back to order=3 then order=2 if no swing found.
    """
    if df.empty or "high" not in df.columns:
        return None
    window = df.tail(lookback).reset_index(drop=True)
    highs = window["high"].tolist()

    for try_order in (order, 3, 2):
        candidates: list[float] = []
        for idx in range(try_order, len(highs) - try_order):
            value = highs[idx]
            if all(value >= highs[idx - step] for step in range(1, try_order + 1)) and all(
                value >= highs[idx + step] for step in range(1, try_order + 1)
            ):
                candidates.append(float(value))
        if candidates:
            return candidates[-1]

    value = float(window["high"].iloc[-min(20, len(window)):].max())
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


STOP_BUFFER_PCT = 0.002  # legacy raw anchor buffer


def compute_structure_levels(
    df: pd.DataFrame,
    entry_price: float,
    direction: str,
    *,
    strategy_name: str = "",
    atr: float | None = None,
) -> StructureLevels:
    """
    Derive structure-based stop and targets from recent swings + Fibonacci levels.

    Stop placement follows K-line structure: the stop goes slightly beyond the
    nearest swing low (LONG) or swing high (SHORT) with a small buffer so
    normal wicks don't trigger it.
    """
    family = normalize_strategy_family(strategy_name)
    fib_levels = _fib_levels(df)
    recent_low = _recent_swing_low(df)
    recent_high = _recent_swing_high(df)

    zone_half_width = _structure_zone_half_width(entry_price, atr, family)
    hard_stop_buffer = _hard_stop_buffer(entry_price, atr, family)

    def _target_zone(anchor: float | None, *, long_side: bool) -> tuple[float | None, float | None, float | None]:
        if anchor is None or anchor <= 0:
            return None, None, None
        zone_low = round(max(anchor - zone_half_width, 0), 4)
        zone_high = round(anchor + zone_half_width, 4)
        if long_side:
            tp = zone_low if zone_low > entry_price else round(anchor, 4)
        else:
            tp = zone_high if zone_high < entry_price else round(anchor, 4)
        return round(tp, 4), zone_low, zone_high

    if direction == "LONG":
        stop_candidates = _pick_levels_below(entry_price, fib_levels, count=2)
        if recent_low is not None and recent_low < entry_price:
            stop_candidates.insert(0, recent_low)
        stop_anchor = max(stop_candidates) if stop_candidates else None
        stop_zone_low = stop_zone_high = stop_loss = hard_stop_loss = None
        if stop_anchor is not None:
            stop_zone_low = round(max(stop_anchor - zone_half_width, 0), 4)
            stop_zone_high = round(stop_anchor + zone_half_width, 4)
            stop_loss = stop_zone_low
            hard_stop_loss = round(max(stop_zone_low - hard_stop_buffer, 0), 4)

        target_candidates = _pick_levels_above(entry_price, fib_levels, count=4)
        if recent_high is not None and recent_high > entry_price:
            target_candidates = sorted({recent_high, *target_candidates})

        tp1, tp1_zone_low, tp1_zone_high = _target_zone(
            target_candidates[0] if len(target_candidates) >= 1 else None,
            long_side=True,
        )
        tp2, tp2_zone_low, tp2_zone_high = _target_zone(
            target_candidates[1] if len(target_candidates) >= 2 else None,
            long_side=True,
        )
        tp3, tp3_zone_low, tp3_zone_high = _target_zone(
            target_candidates[2] if len(target_candidates) >= 3 else None,
            long_side=True,
        )
    else:
        stop_candidates = _pick_levels_above(entry_price, fib_levels, count=2)
        if recent_high is not None and recent_high > entry_price:
            stop_candidates.insert(0, recent_high)
        stop_anchor = min(stop_candidates) if stop_candidates else None
        stop_zone_low = stop_zone_high = stop_loss = hard_stop_loss = None
        if stop_anchor is not None:
            stop_zone_low = round(max(stop_anchor - zone_half_width, 0), 4)
            stop_zone_high = round(stop_anchor + zone_half_width, 4)
            stop_loss = stop_zone_high
            hard_stop_loss = round(stop_zone_high + hard_stop_buffer, 4)

        target_candidates = _pick_levels_below(entry_price, fib_levels, count=4)
        if recent_low is not None and recent_low < entry_price:
            target_candidates = sorted({recent_low, *target_candidates}, reverse=True)

        tp1, tp1_zone_low, tp1_zone_high = _target_zone(
            target_candidates[0] if len(target_candidates) >= 1 else None,
            long_side=False,
        )
        tp2, tp2_zone_low, tp2_zone_high = _target_zone(
            target_candidates[1] if len(target_candidates) >= 2 else None,
            long_side=False,
        )
        tp3, tp3_zone_low, tp3_zone_high = _target_zone(
            target_candidates[2] if len(target_candidates) >= 3 else None,
            long_side=False,
        )

    if family == "mean_reversion":
        tp3 = None
        tp3_zone_low = None
        tp3_zone_high = None

    return StructureLevels(
        stop_loss=stop_loss,
        hard_stop_loss=hard_stop_loss,
        stop_anchor=round(stop_anchor, 4) if stop_anchor is not None else None,
        stop_zone_low=stop_zone_low,
        stop_zone_high=stop_zone_high,
        tp1=tp1,
        tp1_zone_low=tp1_zone_low,
        tp1_zone_high=tp1_zone_high,
        tp2=tp2,
        tp2_zone_low=tp2_zone_low,
        tp2_zone_high=tp2_zone_high,
        tp3=tp3,
        tp3_zone_low=tp3_zone_low,
        tp3_zone_high=tp3_zone_high,
        source="structure",
    )


def _structure_zone_half_width(
    entry_price: float,
    atr: float | None,
    family: str,
) -> float:
    pct_floor = {
        "breakout": 0.0045,
        "trend_following": 0.0035,
        "mean_reversion": 0.0025,
        "default": 0.003,
    }.get(family, 0.003)
    atr_mult = {
        "breakout": 0.8,
        "trend_following": 0.7,
        "mean_reversion": 0.5,
        "default": 0.6,
    }.get(family, 0.6)
    widths = [abs(entry_price) * pct_floor]
    if atr is not None and atr > 0:
        widths.append(abs(atr) * atr_mult)
    return max(widths)


def _hard_stop_buffer(
    entry_price: float,
    atr: float | None,
    family: str,
) -> float:
    pct_floor = {
        "breakout": 0.0025,
        "trend_following": 0.002,
        "mean_reversion": 0.0015,
        "default": 0.002,
    }.get(family, 0.002)
    atr_mult = {
        "breakout": 0.6,
        "trend_following": 0.45,
        "mean_reversion": 0.25,
        "default": 0.4,
    }.get(family, 0.4)
    buffers = [abs(entry_price) * pct_floor]
    if atr is not None and atr > 0:
        buffers.append(abs(atr) * atr_mult)
    return max(buffers)
