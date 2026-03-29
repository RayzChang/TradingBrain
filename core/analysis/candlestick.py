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
  - Pin Bar（關鍵位長影線反轉）
  - Inside Bar（盤整蓄力）
  - Tweezer Top / Bottom（雙針頂/底）
  - 包孕線 (Harami)
  - 烏雲蓋頂 / 穿刺線 (Dark Cloud Cover / Piercing Line)
  - 假突破 (Fakey — Inside Bar 假突破回收)
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
    at_key_level: bool = False


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


def detect_pin_bar(
    row: pd.Series,
    wick_body_ratio: float = 2.5,
    body_position_threshold: float = 0.33,
) -> CandlePattern | None:
    """
    Pin Bar: 長影線 >= 2.5x body，body 在 K 線上/下 1/3 區域。
    比 Hammer 更嚴格 — 強調影線相對 body 的比例和 body 位置。
    """
    o, h, l, c = row["open"], row["high"], row["low"], row["close"]
    full_range = h - l
    if full_range == 0:
        return None

    body = _body(o, c)
    if body == 0:
        return None

    ls = _lower_shadow(l, o, c)
    us = _upper_shadow(h, o, c)
    body_top = max(o, c)
    body_bottom = min(o, c)

    # Bullish pin bar: 長下影線，body 在上 1/3
    if ls >= body * wick_body_ratio and us < body * 0.5:
        body_position = (body_bottom - l) / full_range
        if body_position >= (1 - body_position_threshold):
            confidence = min(ls / body / 4.0, 1.0)
            return CandlePattern(
                name="pin_bar_bullish",
                direction=PatternDirection.BULLISH,
                index=row.name,
                confidence=max(confidence, 0.5),
            )

    # Bearish pin bar: 長上影線，body 在下 1/3
    if us >= body * wick_body_ratio and ls < body * 0.5:
        body_position = (h - body_top) / full_range
        if body_position >= (1 - body_position_threshold):
            confidence = min(us / body / 4.0, 1.0)
            return CandlePattern(
                name="pin_bar_bearish",
                direction=PatternDirection.BEARISH,
                index=row.name,
                confidence=max(confidence, 0.5),
            )

    return None


def detect_inside_bar(
    curr: pd.Series,
    prev: pd.Series,
) -> CandlePattern | None:
    """
    Inside Bar: 本根 K 線的高低完全在前一根範圍內。
    代表盤整蓄力，方向 NEUTRAL（等待突破方向確認）。
    """
    ch, cl = curr["high"], curr["low"]
    ph, pl = prev["high"], prev["low"]

    if ch <= ph and cl >= pl:
        prev_range = ph - pl
        curr_range = ch - cl
        if prev_range <= 0:
            return None
        compression = 1.0 - (curr_range / prev_range)
        return CandlePattern(
            name="inside_bar",
            direction=PatternDirection.NEUTRAL,
            index=curr.name,
            confidence=min(max(compression, 0.4), 0.9),
        )
    return None


def detect_tweezer(
    curr: pd.Series,
    prev: pd.Series,
    tolerance_pct: float = 0.001,
) -> CandlePattern | None:
    """
    Tweezer Top: 兩根 K 線 high 幾乎相同（差距 < 0.1%），第一根陽第二根陰。
    Tweezer Bottom: 兩根 K 線 low 幾乎相同，第一根陰第二根陽。
    """
    ch, cl, co, cc = curr["high"], curr["low"], curr["open"], curr["close"]
    ph, pl, po, pc = prev["high"], prev["low"], prev["open"], prev["close"]

    ref_price = max(ch, ph)
    if ref_price <= 0:
        return None

    # Tweezer Top
    if abs(ch - ph) / ref_price <= tolerance_pct:
        if _is_bullish(po, pc) and not _is_bullish(co, cc):
            return CandlePattern(
                name="tweezer_top",
                direction=PatternDirection.BEARISH,
                index=curr.name,
                confidence=0.7,
            )

    # Tweezer Bottom
    ref_low = max(min(cl, pl), 1e-9)
    if abs(cl - pl) / ref_low <= tolerance_pct:
        if not _is_bullish(po, pc) and _is_bullish(co, cc):
            return CandlePattern(
                name="tweezer_bottom",
                direction=PatternDirection.BULLISH,
                index=curr.name,
                confidence=0.7,
            )

    return None


def detect_harami(
    curr: pd.Series,
    prev: pd.Series,
) -> CandlePattern | None:
    """
    包孕線 (Harami): 本根 body 完全在前根 body 內，前根 body > 2x 本根。
    方向與前根相反（反轉信號）。
    """
    co, cc = curr["open"], curr["close"]
    po, pc = prev["open"], prev["close"]

    prev_body = _body(po, pc)
    curr_body = _body(co, cc)

    if prev_body == 0 or curr_body == 0:
        return None
    if prev_body < curr_body * 2:
        return None

    curr_body_high = max(co, cc)
    curr_body_low = min(co, cc)
    prev_body_high = max(po, pc)
    prev_body_low = min(po, pc)

    if curr_body_high <= prev_body_high and curr_body_low >= prev_body_low:
        confidence = min(prev_body / max(curr_body, 0.001) / 5.0, 0.85)
        confidence = max(confidence, 0.5)
        if _is_bullish(po, pc):
            return CandlePattern(
                name="bearish_harami",
                direction=PatternDirection.BEARISH,
                index=curr.name,
                confidence=confidence,
            )
        else:
            return CandlePattern(
                name="bullish_harami",
                direction=PatternDirection.BULLISH,
                index=curr.name,
                confidence=confidence,
            )
    return None


def detect_dark_cloud_piercing(
    curr: pd.Series,
    prev: pd.Series,
) -> CandlePattern | None:
    """
    烏雲蓋頂 (Dark Cloud Cover): 前陽後陰，後根開盤 > 前根 high，
    收盤穿入前根 body 50% 以下。
    穿刺線 (Piercing Line): 前陰後陽，後根開盤 < 前根 low，
    收盤穿入前根 body 50% 以上。
    """
    co, cc = curr["open"], curr["close"]
    po, pc = prev["open"], prev["close"]

    prev_body = _body(po, pc)
    if prev_body == 0:
        return None

    prev_mid = (po + pc) / 2

    # Dark Cloud Cover
    if _is_bullish(po, pc) and not _is_bullish(co, cc):
        if co >= prev.get("high", pc) and cc < prev_mid and cc > po:
            return CandlePattern(
                name="dark_cloud_cover",
                direction=PatternDirection.BEARISH,
                index=curr.name,
                confidence=0.75,
            )

    # Piercing Line
    if not _is_bullish(po, pc) and _is_bullish(co, cc):
        if co <= prev.get("low", pc) and cc > prev_mid and cc < po:
            return CandlePattern(
                name="piercing_line",
                direction=PatternDirection.BULLISH,
                index=curr.name,
                confidence=0.75,
            )

    return None


def detect_fakey(df: pd.DataFrame, idx: int) -> CandlePattern | None:
    """
    假突破 (Fakey): Inside Bar 後的假突破回收（3 根 K 線組合）。
    - K0: 母線 (mother bar)
    - K1: Inside bar (完全在 K0 範圍內)
    - K2: 假突破後回收 — 突破 K0 範圍但收盤回到 K0 範圍內

    Bullish Fakey: K2 low < K0 low (假突破下方) 但 close > K0 low
    Bearish Fakey: K2 high > K0 high (假突破上方) 但 close < K0 high
    """
    if idx < 2:
        return None

    k0 = df.iloc[idx - 2]
    k1 = df.iloc[idx - 1]
    k2 = df.iloc[idx]

    # K1 must be inside bar of K0
    if k1["high"] > k0["high"] or k1["low"] < k0["low"]:
        return None

    # Bullish Fakey: K2 假突破下方但收回
    if k2["low"] < k0["low"] and k2["close"] > k0["low"] and k2["close"] > k2["open"]:
        return CandlePattern(
            name="bullish_fakey",
            direction=PatternDirection.BULLISH,
            index=idx,
            confidence=0.85,
        )

    # Bearish Fakey: K2 假突破上方但收回
    if k2["high"] > k0["high"] and k2["close"] < k0["high"] and k2["close"] < k2["open"]:
        return CandlePattern(
            name="bearish_fakey",
            direction=PatternDirection.BEARISH,
            index=idx,
            confidence=0.85,
        )

    return None


def detect_all_patterns(
    df: pd.DataFrame,
    lookback: int = 10,
) -> list[CandlePattern]:
    """
    偵測最近 lookback 根 K 線中的所有 K 線型態。
    包含量能加權：volume > 1.5x avg → confidence *= 1.15；< 0.5x avg → confidence *= 0.7

    Returns:
        list of CandlePattern
    """
    if len(df) < 3:
        return []

    start = max(0, len(df) - lookback)
    patterns: list[CandlePattern] = []

    # 計算量能均值（用於加權）
    has_volume = "volume" in df.columns
    avg_volume: float = 0.0
    if has_volume:
        vol_series = df["volume"].iloc[max(0, start - 20):len(df)]
        vol_numeric = pd.to_numeric(vol_series, errors="coerce")
        avg_volume = float(vol_numeric.mean()) if len(vol_numeric) > 0 else 0.0

    for i in range(start, len(df)):
        row = df.iloc[i]
        row_patterns: list[CandlePattern] = []

        # --- 單根 K 線型態 ---
        p = detect_doji(row)
        if p:
            row_patterns.append(p)

        p = detect_hammer(row)
        if p:
            row_patterns.append(p)

        p = detect_pin_bar(row)
        if p:
            row_patterns.append(p)

        # --- 雙根 K 線型態 ---
        if i > 0:
            prev = df.iloc[i - 1]

            p = detect_engulfing(row, prev)
            if p:
                row_patterns.append(p)

            p = detect_inside_bar(row, prev)
            if p:
                row_patterns.append(p)

            p = detect_tweezer(row, prev)
            if p:
                row_patterns.append(p)

            p = detect_harami(row, prev)
            if p:
                row_patterns.append(p)

            p = detect_dark_cloud_piercing(row, prev)
            if p:
                row_patterns.append(p)

        # --- 三根 K 線組合型態 ---
        if i >= 2:
            p = detect_three_soldiers(df, i)
            if p:
                row_patterns.append(p)

            p = detect_morning_evening_star(df, i)
            if p:
                row_patterns.append(p)

            p = detect_fakey(df, i)
            if p:
                row_patterns.append(p)

        # --- 量能加權 ---
        if has_volume and avg_volume > 0:
            row_vol = pd.to_numeric(row.get("volume", 0), errors="coerce")
            if not np.isnan(row_vol) and row_vol > 0:
                vol_ratio = row_vol / avg_volume
                if vol_ratio >= 1.5:
                    for rp in row_patterns:
                        rp.confidence = min(rp.confidence * 1.15, 1.0)
                elif vol_ratio <= 0.5:
                    for rp in row_patterns:
                        rp.confidence = rp.confidence * 0.7

        patterns.extend(row_patterns)

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
