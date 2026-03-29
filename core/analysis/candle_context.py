"""
多 K 線上下文分析模組

分析最近 N 根 K 線的整體行為：動量方向、影線拒絕、body 成長趨勢、量能趨勢。
用於策略層判斷「K 線群體在說什麼」，而非只看單根型態。
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class CandleContext:
    """多根 K 線的上下文摘要。"""

    momentum_score: float  # -1.0 (極度看空) ~ +1.0 (極度看多)
    rejection_count: int  # 影線在同價位拒絕的次數
    body_progression: str  # "growing" / "shrinking" / "mixed"
    volume_trend: str  # "rising" / "falling" / "flat"
    dominant_direction: str  # "bullish" / "bearish" / "neutral"


def analyze_candle_context(df: pd.DataFrame, lookback: int = 8) -> CandleContext:
    """
    分析最近 lookback 根 K 線的整體上下文。

    Args:
        df: OHLCV DataFrame（需有 open, high, low, close 欄位，volume 可選）
        lookback: 回溯根數，預設 8

    Returns:
        CandleContext 摘要
    """
    if df is None or len(df) < 2:
        return CandleContext(
            momentum_score=0.0,
            rejection_count=0,
            body_progression="mixed",
            volume_trend="flat",
            dominant_direction="neutral",
        )

    window = df.tail(lookback).copy()
    n = len(window)

    # --- 1. Momentum Score ---
    # 每根 K 線的 body 方向加權：陽線 +1, 陰線 -1, 越近的權重越大
    bodies = window["close"].values - window["open"].values
    weights = np.linspace(0.5, 1.5, n)  # 越近權重越高
    ranges = window["high"].values - window["low"].values
    safe_ranges = np.where(ranges > 0, ranges, 1e-9)

    # body 佔 range 的比例 * 方向
    body_ratios = bodies / safe_ranges  # -1 ~ +1
    momentum_score = float(np.average(body_ratios, weights=weights))
    momentum_score = max(-1.0, min(1.0, momentum_score))

    # --- 2. Rejection Count ---
    # 計算影線在相近價位（0.3% 內）拒絕的次數
    rejection_count = 0
    latest_close = float(window["close"].iloc[-1])
    threshold = latest_close * 0.003 if latest_close > 0 else 0

    for i in range(n):
        row = window.iloc[i]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        body_bottom = min(o, c)
        body_top = max(o, c)
        lower_wick = body_bottom - l
        upper_wick = h - body_top
        body = abs(c - o)
        safe_body = max(body, 1e-9)

        # 下影線拒絕（在近期低點附近）
        if lower_wick >= safe_body * 1.0 and l <= float(window["low"].min()) + threshold:
            rejection_count += 1
        # 上影線拒絕（在近期高點附近）
        if upper_wick >= safe_body * 1.0 and h >= float(window["high"].max()) - threshold:
            rejection_count += 1

    # --- 3. Body Progression ---
    body_sizes = np.abs(bodies)
    if n >= 3:
        first_half = body_sizes[: n // 2]
        second_half = body_sizes[n // 2:]
        avg_first = float(np.mean(first_half)) if len(first_half) > 0 else 0
        avg_second = float(np.mean(second_half)) if len(second_half) > 0 else 0
        if avg_first > 0:
            change_ratio = avg_second / avg_first
            if change_ratio >= 1.3:
                body_progression = "growing"
            elif change_ratio <= 0.7:
                body_progression = "shrinking"
            else:
                body_progression = "mixed"
        else:
            body_progression = "mixed"
    else:
        body_progression = "mixed"

    # --- 4. Volume Trend ---
    has_volume = "volume" in window.columns
    if has_volume and n >= 3:
        vol = pd.to_numeric(window["volume"], errors="coerce").values
        if not np.all(np.isnan(vol)):
            vol_first = float(np.nanmean(vol[: n // 2]))
            vol_second = float(np.nanmean(vol[n // 2:]))
            if vol_first > 0:
                vol_change = vol_second / vol_first
                if vol_change >= 1.3:
                    volume_trend = "rising"
                elif vol_change <= 0.7:
                    volume_trend = "falling"
                else:
                    volume_trend = "flat"
            else:
                volume_trend = "flat"
        else:
            volume_trend = "flat"
    else:
        volume_trend = "flat"

    # --- 5. Dominant Direction ---
    bullish_count = int(np.sum(bodies > 0))
    bearish_count = int(np.sum(bodies < 0))

    if momentum_score >= 0.2 and bullish_count >= n * 0.6:
        dominant_direction = "bullish"
    elif momentum_score <= -0.2 and bearish_count >= n * 0.6:
        dominant_direction = "bearish"
    else:
        dominant_direction = "neutral"

    return CandleContext(
        momentum_score=round(momentum_score, 4),
        rejection_count=rejection_count,
        body_progression=body_progression,
        volume_trend=volume_trend,
        dominant_direction=dominant_direction,
    )
