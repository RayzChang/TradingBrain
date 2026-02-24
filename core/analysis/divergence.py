"""
背離偵測模組

偵測價格與指標（RSI / MACD）之間的背離：
- 看漲背離 (Bullish Divergence): 價格創新低，指標不創新低 → 可能反轉上漲
- 看跌背離 (Bearish Divergence): 價格創新高，指標不創新高 → 可能反轉下跌
- 隱藏背離 (Hidden Divergence): 趨勢延續信號

使用 swing high/low 偵測法，避免雜訊。
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd
from loguru import logger


class DivergenceType(str, Enum):
    REGULAR_BULLISH = "regular_bullish"
    REGULAR_BEARISH = "regular_bearish"
    HIDDEN_BULLISH = "hidden_bullish"
    HIDDEN_BEARISH = "hidden_bearish"


@dataclass
class Divergence:
    type: DivergenceType
    indicator: str
    start_idx: int
    end_idx: int
    price_start: float
    price_end: float
    indicator_start: float
    indicator_end: float
    strength: float  # 0.0 ~ 1.0


def find_swing_lows(series: pd.Series, order: int = 5) -> list[int]:
    """找出局部低點 (swing low)"""
    lows = []
    arr = series.values
    for i in range(order, len(arr) - order):
        if all(arr[i] <= arr[i - j] for j in range(1, order + 1)) and \
           all(arr[i] <= arr[i + j] for j in range(1, order + 1)):
            lows.append(i)
    return lows


def find_swing_highs(series: pd.Series, order: int = 5) -> list[int]:
    """找出局部高點 (swing high)"""
    highs = []
    arr = series.values
    for i in range(order, len(arr) - order):
        if all(arr[i] >= arr[i - j] for j in range(1, order + 1)) and \
           all(arr[i] >= arr[i + j] for j in range(1, order + 1)):
            highs.append(i)
    return highs


def _calc_strength(
    price_change_pct: float,
    indicator_change_pct: float,
) -> float:
    """
    計算背離強度。
    價格與指標的背離幅度越大，信號越強。
    """
    divergence_gap = abs(price_change_pct - indicator_change_pct)
    return min(divergence_gap / 20.0, 1.0)


def detect_rsi_divergence(
    df: pd.DataFrame,
    lookback: int = 60,
    swing_order: int = 5,
) -> list[Divergence]:
    """
    偵測 RSI 背離。

    Args:
        df: 需包含 close, rsi 欄位
        lookback: 回溯多少根 K 線
        swing_order: swing high/low 判定的鄰近 K 線數

    Returns:
        list of Divergence objects
    """
    if "rsi" not in df.columns or len(df) < lookback:
        return []

    window = df.iloc[-lookback:].copy()
    window = window.reset_index(drop=True)
    close = window["close"]
    rsi = window["rsi"]

    divergences = []

    # --- Regular Bullish: 價格新低，RSI 不新低 ---
    price_lows = find_swing_lows(close, swing_order)
    rsi_lows = find_swing_lows(rsi, swing_order)

    if len(price_lows) >= 2:
        p1, p2 = price_lows[-2], price_lows[-1]
        if close.iloc[p2] < close.iloc[p1]:
            r1_candidates = [r for r in rsi_lows if abs(r - p1) <= swing_order + 2]
            r2_candidates = [r for r in rsi_lows if abs(r - p2) <= swing_order + 2]
            if r1_candidates and r2_candidates:
                r1, r2 = r1_candidates[-1], r2_candidates[-1]
                if rsi.iloc[r2] > rsi.iloc[r1]:
                    price_pct = (close.iloc[p2] - close.iloc[p1]) / close.iloc[p1] * 100
                    rsi_pct = (rsi.iloc[r2] - rsi.iloc[r1]) / max(rsi.iloc[r1], 1) * 100
                    divergences.append(Divergence(
                        type=DivergenceType.REGULAR_BULLISH,
                        indicator="rsi",
                        start_idx=p1, end_idx=p2,
                        price_start=close.iloc[p1], price_end=close.iloc[p2],
                        indicator_start=rsi.iloc[r1], indicator_end=rsi.iloc[r2],
                        strength=_calc_strength(price_pct, rsi_pct),
                    ))

    # --- Regular Bearish: 價格新高，RSI 不新高 ---
    price_highs = find_swing_highs(close, swing_order)
    rsi_highs = find_swing_highs(rsi, swing_order)

    if len(price_highs) >= 2:
        p1, p2 = price_highs[-2], price_highs[-1]
        if close.iloc[p2] > close.iloc[p1]:
            r1_candidates = [r for r in rsi_highs if abs(r - p1) <= swing_order + 2]
            r2_candidates = [r for r in rsi_highs if abs(r - p2) <= swing_order + 2]
            if r1_candidates and r2_candidates:
                r1, r2 = r1_candidates[-1], r2_candidates[-1]
                if rsi.iloc[r2] < rsi.iloc[r1]:
                    price_pct = (close.iloc[p2] - close.iloc[p1]) / close.iloc[p1] * 100
                    rsi_pct = (rsi.iloc[r2] - rsi.iloc[r1]) / max(rsi.iloc[r1], 1) * 100
                    divergences.append(Divergence(
                        type=DivergenceType.REGULAR_BEARISH,
                        indicator="rsi",
                        start_idx=p1, end_idx=p2,
                        price_start=close.iloc[p1], price_end=close.iloc[p2],
                        indicator_start=rsi.iloc[r1], indicator_end=rsi.iloc[r2],
                        strength=_calc_strength(price_pct, rsi_pct),
                    ))

    return divergences


def detect_macd_divergence(
    df: pd.DataFrame,
    lookback: int = 60,
    swing_order: int = 5,
) -> list[Divergence]:
    """
    偵測 MACD 柱狀圖背離。

    Args:
        df: 需包含 close, macd_hist 欄位
        lookback: 回溯多少根 K 線
        swing_order: swing high/low 判定的鄰近 K 線數

    Returns:
        list of Divergence objects
    """
    if "macd_hist" not in df.columns or len(df) < lookback:
        return []

    window = df.iloc[-lookback:].copy()
    window = window.reset_index(drop=True)
    close = window["close"]
    macd_h = window["macd_hist"]

    divergences = []

    # --- Regular Bullish ---
    price_lows = find_swing_lows(close, swing_order)
    macd_lows = find_swing_lows(macd_h, swing_order)

    if len(price_lows) >= 2:
        p1, p2 = price_lows[-2], price_lows[-1]
        if close.iloc[p2] < close.iloc[p1]:
            m1_cands = [m for m in macd_lows if abs(m - p1) <= swing_order + 2]
            m2_cands = [m for m in macd_lows if abs(m - p2) <= swing_order + 2]
            if m1_cands and m2_cands:
                m1, m2 = m1_cands[-1], m2_cands[-1]
                if macd_h.iloc[m2] > macd_h.iloc[m1]:
                    price_pct = (close.iloc[p2] - close.iloc[p1]) / close.iloc[p1] * 100
                    macd_pct = abs(macd_h.iloc[m2]) - abs(macd_h.iloc[m1])
                    divergences.append(Divergence(
                        type=DivergenceType.REGULAR_BULLISH,
                        indicator="macd",
                        start_idx=p1, end_idx=p2,
                        price_start=close.iloc[p1], price_end=close.iloc[p2],
                        indicator_start=macd_h.iloc[m1], indicator_end=macd_h.iloc[m2],
                        strength=_calc_strength(price_pct, macd_pct),
                    ))

    # --- Regular Bearish ---
    price_highs = find_swing_highs(close, swing_order)
    macd_highs = find_swing_highs(macd_h, swing_order)

    if len(price_highs) >= 2:
        p1, p2 = price_highs[-2], price_highs[-1]
        if close.iloc[p2] > close.iloc[p1]:
            m1_cands = [m for m in macd_highs if abs(m - p1) <= swing_order + 2]
            m2_cands = [m for m in macd_highs if abs(m - p2) <= swing_order + 2]
            if m1_cands and m2_cands:
                m1, m2 = m1_cands[-1], m2_cands[-1]
                if macd_h.iloc[m2] < macd_h.iloc[m1]:
                    price_pct = (close.iloc[p2] - close.iloc[p1]) / close.iloc[p1] * 100
                    macd_pct = abs(macd_h.iloc[m2]) - abs(macd_h.iloc[m1])
                    divergences.append(Divergence(
                        type=DivergenceType.REGULAR_BEARISH,
                        indicator="macd",
                        start_idx=p1, end_idx=p2,
                        price_start=close.iloc[p1], price_end=close.iloc[p2],
                        indicator_start=macd_h.iloc[m1], indicator_end=macd_h.iloc[m2],
                        strength=_calc_strength(price_pct, macd_pct),
                    ))

    return divergences


def detect_all_divergences(
    df: pd.DataFrame,
    lookback: int = 60,
    swing_order: int = 5,
) -> list[Divergence]:
    """偵測所有背離信號 (RSI + MACD)"""
    results = []
    results.extend(detect_rsi_divergence(df, lookback, swing_order))
    results.extend(detect_macd_divergence(df, lookback, swing_order))
    if results:
        logger.info(f"Detected {len(results)} divergence(s): "
                     f"{[d.type.value for d in results]}")
    return results
