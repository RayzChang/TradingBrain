"""
斐波那契回撤 / 擴展模組

根據最近一段 swing high → swing low（下跌趨勢）或
swing low → swing high（上漲趨勢）計算關鍵支撐/阻力位。

標準回撤位: 0.236, 0.382, 0.5, 0.618, 0.786
擴展位: 1.0, 1.272, 1.618, 2.0, 2.618
"""

from dataclasses import dataclass, field

import pandas as pd
from loguru import logger

RETRACEMENT_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
EXTENSION_LEVELS = [1.0, 1.272, 1.618, 2.0, 2.618]


@dataclass
class FibonacciResult:
    trend: str  # "UP" or "DOWN"
    swing_high: float
    swing_low: float
    swing_high_idx: int
    swing_low_idx: int
    retracement: dict[float, float] = field(default_factory=dict)
    extension: dict[float, float] = field(default_factory=dict)


def _find_major_swing(
    df: pd.DataFrame,
    lookback: int = 100,
) -> tuple[int, float, int, float]:
    """
    在 lookback 區間內找出最顯著的 swing high 和 swing low。

    Returns:
        (high_idx, high_price, low_idx, low_price)
    """
    window = df.iloc[-lookback:]
    high_idx = window["high"].idxmax()
    low_idx = window["low"].idxmin()
    return (
        high_idx,
        window.loc[high_idx, "high"],
        low_idx,
        window.loc[low_idx, "low"],
    )


def calculate_fibonacci(
    df: pd.DataFrame,
    lookback: int = 100,
) -> FibonacciResult | None:
    """
    計算斐波那契回撤位和擴展位。

    Args:
        df: 需包含 high, low 欄位
        lookback: 回溯多少根 K 線來找 swing

    Returns:
        FibonacciResult or None
    """
    if len(df) < lookback:
        lookback = len(df)
    if lookback < 20:
        return None

    high_idx, high_price, low_idx, low_price = _find_major_swing(df, lookback)

    if high_price == low_price:
        return None

    diff = high_price - low_price

    # 判定趨勢方向: swing low 在 swing high 之前 → 上漲趨勢，反之下跌
    if low_idx < high_idx:
        trend = "UP"
        retracement = {
            level: high_price - diff * level
            for level in RETRACEMENT_LEVELS
        }
        extension = {
            level: high_price + diff * (level - 1.0)
            for level in EXTENSION_LEVELS
        }
    else:
        trend = "DOWN"
        retracement = {
            level: low_price + diff * level
            for level in RETRACEMENT_LEVELS
        }
        extension = {
            level: low_price - diff * (level - 1.0)
            for level in EXTENSION_LEVELS
        }

    result = FibonacciResult(
        trend=trend,
        swing_high=high_price,
        swing_low=low_price,
        swing_high_idx=int(high_idx),
        swing_low_idx=int(low_idx),
        retracement=retracement,
        extension=extension,
    )

    return result


def find_nearest_fib_levels(
    fib: FibonacciResult,
    current_price: float,
) -> dict[str, tuple[float, float] | None]:
    """
    找出離當前價格最近的支撐位和阻力位。

    Returns:
        {
          "support": (level_pct, price) or None,
          "resistance": (level_pct, price) or None,
        }
    """
    all_levels = list(fib.retracement.items()) + list(fib.extension.items())
    all_levels.sort(key=lambda x: x[1])

    support = None
    resistance = None

    for level, price in all_levels:
        if price < current_price:
            support = (level, price)
        elif price > current_price and resistance is None:
            resistance = (level, price)

    return {"support": support, "resistance": resistance}


def get_fib_summary(df: pd.DataFrame, lookback: int = 100) -> dict:
    """
    計算 Fibonacci 並返回精簡摘要。
    """
    fib = calculate_fibonacci(df, lookback)
    if fib is None:
        return {"available": False}

    current_price = df["close"].iloc[-1]
    nearest = find_nearest_fib_levels(fib, current_price)

    summary = {
        "available": True,
        "trend": fib.trend,
        "swing_high": fib.swing_high,
        "swing_low": fib.swing_low,
        "retracement_levels": {
            f"{k:.1%}": round(v, 4) for k, v in fib.retracement.items()
        },
        "nearest_support": (
            {"level": f"{nearest['support'][0]:.1%}", "price": round(nearest["support"][1], 4)}
            if nearest["support"] else None
        ),
        "nearest_resistance": (
            {"level": f"{nearest['resistance'][0]:.1%}", "price": round(nearest["resistance"][1], 4)}
            if nearest["resistance"] else None
        ),
    }
    return summary
