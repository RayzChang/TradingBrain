"""
K 線型態辨識模組

辨識常見的 K 線型態（candlestick patterns），用於輔助進出場決策。
所有辨識基於純 Python 計算，不依賴外部型態庫。

支援型態:
  - 十字星 (Doji)
  - 錘子線 (Hammer) / 倒錘子 (Inverted Hammer)
  - 吞噬 (Engulfing)
  - 晨星 (Morning Star) / 夜星 (Evening Star)
  - 三兵 (Three Soldiers / Three Crows)
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd
from loguru import logger


class PatternDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class CandlePattern:
    name: str
    direction: PatternDirection
    index: int
    confidence: float  # 0.0 ~ 1.0


def _body(o: float, c: float) -> float:
    return abs(c - o)


def _upper_shadow(h: float, o: float, c: float) -> float:
    return h - max(o, c)


def _lower_shadow(l: float, o: float, c: float) -> float:
    return min(o, c) - l


def _is_bullish(o: float, c: float) -> bool:
    return c > o


def detect_doji(
    row: pd.Series,
    body_ratio_threshold: float = 0.05,
) -> CandlePattern | None:
    """
    十字星: 實體很小（< 5% of high-low range）
    表示市場猶豫不決。
    """
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    full_range = h - l
    if full_range == 0:
        return None

    body = _body(o, c)
    if body / full_range < body_ratio_threshold:
        return CandlePattern(
            name="doji", direction=PatternDirection.NEUTRAL,
            index=row.name, confidence=1.0 - (body / full_range),
        )
    return None


def detect_hammer(
    row: pd.Series,
    body_ratio_max: float = 0.3,
    lower_shadow_ratio_min: float = 2.0,
) -> CandlePattern | None:
    """
    錘子線: 長下影線（>= 2x 實體），短上影線，出現在下跌趨勢底部。
    倒錘子: 長上影線，短下影線。
    """
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    body = _body(o, c)
    if body == 0:
        return None

    us = _upper_shadow(h, o, c)
    ls = _lower_shadow(l, o, c)
    full_range = h - l
    if full_range == 0:
        return None

    if body / full_range <= body_ratio_max:
        if ls >= body * lower_shadow_ratio_min and us < body:
            return CandlePattern(
                name="hammer",
                direction=PatternDirection.BULLISH,
                index=row.name,
                confidence=min(ls / body / 3.0, 1.0),
            )
        if us >= body * lower_shadow_ratio_min and ls < body:
            return CandlePattern(
                name="inverted_hammer",
                direction=PatternDirection.BEARISH,
                index=row.name,
                confidence=min(us / body / 3.0, 1.0),
            )
    return None


def detect_engulfing(
    curr: pd.Series,
    prev: pd.Series,
) -> CandlePattern | None:
    """
    吞噬型態:
    - 看漲吞噬: 前一根陰線，本根陽線完全包裹前根實體
    - 看跌吞噬: 前一根陽線，本根陰線完全包裹前根實體
    """
    co, cc = curr["open"], curr["close"]
    po, pc = prev["open"], prev["close"]

    prev_body = _body(po, pc)
    curr_body = _body(co, cc)

    if curr_body <= prev_body:
        return None

    if not _is_bullish(po, pc) and _is_bullish(co, cc):
        if co <= pc and cc >= po:
            return CandlePattern(
                name="bullish_engulfing",
                direction=PatternDirection.BULLISH,
                index=curr.name,
                confidence=min(curr_body / max(prev_body, 0.001) / 3.0, 1.0),
            )

    if _is_bullish(po, pc) and not _is_bullish(co, cc):
        if co >= pc and cc <= po:
            return CandlePattern(
                name="bearish_engulfing",
                direction=PatternDirection.BEARISH,
                index=curr.name,
                confidence=min(curr_body / max(prev_body, 0.001) / 3.0, 1.0),
            )

    return None


def detect_three_soldiers(df: pd.DataFrame, idx: int) -> CandlePattern | None:
    """
    三白兵 (Three White Soldiers): 連續三根陽線，每根開盤在前一根實體內，收盤創新高。
    三黑鴉 (Three Black Crows): 反向。
    """
    if idx < 2:
        return None

    c0 = df.iloc[idx - 2]
    c1 = df.iloc[idx - 1]
    c2 = df.iloc[idx]

    b0 = _is_bullish(c0["open"], c0["close"])
    b1 = _is_bullish(c1["open"], c1["close"])
    b2 = _is_bullish(c2["open"], c2["close"])

    if b0 and b1 and b2:
        if (c1["close"] > c0["close"] and c2["close"] > c1["close"] and
                c1["open"] > c0["open"] and c2["open"] > c1["open"]):
            return CandlePattern(
                name="three_white_soldiers",
                direction=PatternDirection.BULLISH,
                index=idx,
                confidence=0.8,
            )

    if not b0 and not b1 and not b2:
        if (c1["close"] < c0["close"] and c2["close"] < c1["close"] and
                c1["open"] < c0["open"] and c2["open"] < c1["open"]):
            return CandlePattern(
                name="three_black_crows",
                direction=PatternDirection.BEARISH,
                index=idx,
                confidence=0.8,
            )

    return None


def detect_morning_evening_star(df: pd.DataFrame, idx: int) -> CandlePattern | None:
    """
    晨星 / 夜星（三根 K 線組合型態）。
    晨星: 長陰 → 小實體 → 長陽
    夜星: 長陽 → 小實體 → 長陰
    """
    if idx < 2:
        return None

    c0 = df.iloc[idx - 2]
    c1 = df.iloc[idx - 1]
    c2 = df.iloc[idx]

    body0 = _body(c0["open"], c0["close"])
    body1 = _body(c1["open"], c1["close"])
    body2 = _body(c2["open"], c2["close"])

    avg_body = (body0 + body2) / 2
    if avg_body == 0:
        return None

    small_body = body1 < avg_body * 0.3

    if not small_body:
        return None

    # 晨星
    if (not _is_bullish(c0["open"], c0["close"]) and
            _is_bullish(c2["open"], c2["close"]) and
            body0 > 0 and body2 > 0):
        if c2["close"] > (c0["open"] + c0["close"]) / 2:
            return CandlePattern(
                name="morning_star",
                direction=PatternDirection.BULLISH,
                index=idx,
                confidence=0.75,
            )

    # 夜星
    if (_is_bullish(c0["open"], c0["close"]) and
            not _is_bullish(c2["open"], c2["close"]) and
            body0 > 0 and body2 > 0):
        if c2["close"] < (c0["open"] + c0["close"]) / 2:
            return CandlePattern(
                name="evening_star",
                direction=PatternDirection.BEARISH,
                index=idx,
                confidence=0.75,
            )

    return None


def detect_all_patterns(
    df: pd.DataFrame,
    lookback: int = 10,
) -> list[CandlePattern]:
    """
    偵測最近 lookback 根 K 線中的所有 K 線型態。

    Returns:
        list of CandlePattern
    """
    if len(df) < 3:
        return []

    start = max(0, len(df) - lookback)
    patterns: list[CandlePattern] = []

    for i in range(start, len(df)):
        row = df.iloc[i]

        p = detect_doji(row)
        if p:
            patterns.append(p)

        p = detect_hammer(row)
        if p:
            patterns.append(p)

        if i > 0:
            p = detect_engulfing(df.iloc[i], df.iloc[i - 1])
            if p:
                patterns.append(p)

        if i >= 2:
            p = detect_three_soldiers(df, i)
            if p:
                patterns.append(p)

            p = detect_morning_evening_star(df, i)
            if p:
                patterns.append(p)

    if patterns:
        logger.debug(f"Detected {len(patterns)} candle pattern(s) in last {lookback} candles")

    return patterns


def get_latest_pattern_signal(df: pd.DataFrame) -> dict:
    """
    取得最新一根 K 線上的型態信號摘要。
    """
    patterns = detect_all_patterns(df, lookback=5)
    if not patterns:
        return {"pattern": None, "direction": "neutral", "confidence": 0}

    latest = patterns[-1]
    return {
        "pattern": latest.name,
        "direction": latest.direction.value,
        "confidence": round(latest.confidence, 2),
    }
