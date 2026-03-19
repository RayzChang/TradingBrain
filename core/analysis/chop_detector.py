"""
絞肉機偵測模組 (Chop / Whipsaw Detector)

偵測市場是否處於「絞肉機行情」— 價格劇烈震盪但沒有方向，
頻繁觸發止損，是小資金的天敵。

偵測方法:
  1. ATR 突增但趨勢弱 (ADX < 20)
  2. 上下影線比例異常高
  3. 連續假突破（突破後快速回撤）
  4. 布林帶寬度壓縮後的擴張方向不明確

觸發「絞肉機暫停」後，系統應暫停開新倉 1~2 小時。
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from loguru import logger


@dataclass
class ChopResult:
    is_chop: bool
    score: float  # 0.0 (非常順暢) ~ 1.0 (極度絞肉)
    reasons: list[str]
    cooldown_minutes: int  # 建議暫停分鐘數


def _wick_ratio(df: pd.DataFrame, lookback: int = 15) -> float:
    """
    計算最近 lookback 根 K 線的平均影線佔比。
    高影線佔比 = 市場多空交戰激烈。
    """
    window = df.iloc[-lookback:]
    total_range = (window["high"] - window["low"]).replace(0, np.nan)
    body = abs(window["close"] - window["open"])
    wick = total_range - body
    ratio = (wick / total_range).mean()
    return float(ratio) if not np.isnan(ratio) else 0.0


def _false_breakout_count(
    df: pd.DataFrame,
    lookback: int = 20,
    threshold_pct: float = 0.3,
) -> int:
    """
    計算假突破次數。
    定義: K 線的高點突破前一根高點，但收盤價回落到前一根高點以下。
    """
    window = df.iloc[-lookback:]
    count = 0
    for i in range(1, len(window)):
        prev = window.iloc[i - 1]
        curr = window.iloc[i]
        body_pct = abs(curr["close"] - curr["open"]) / max(curr["open"], 0.001) * 100

        if curr["high"] > prev["high"] and curr["close"] < prev["high"]:
            count += 1
        if curr["low"] < prev["low"] and curr["close"] > prev["low"]:
            count += 1

    return count


def _price_displacement(df: pd.DataFrame, lookback: int = 15) -> float:
    """
    價格位移率: 淨價格變化 / 總移動路徑。
    趨勢市場接近 1.0，震盪市場接近 0.0。
    """
    window = df.iloc[-lookback:]
    if len(window) < 2:
        return 1.0

    net_change = abs(window["close"].iloc[-1] - window["close"].iloc[0])
    total_path = abs(window["close"].diff()).sum()

    if total_path == 0:
        return 1.0

    return float(net_change / total_path)


def detect_chop(
    df: pd.DataFrame,
    lookback: int = 20,
    adx_threshold: float = 17.0,
    wick_threshold: float = 0.65,
    displacement_threshold: float = 0.15,
    false_breakout_threshold: int = 6,
) -> ChopResult:
    """
    綜合偵測是否為絞肉機行情。

    Args:
        df: 需包含 high, low, close, open, adx, atr 欄位
        lookback: 回溯 K 線數
        adx_threshold: ADX 低於此值視為無趨勢
        wick_threshold: 影線佔比高於此值視為交戰激烈
        displacement_threshold: 位移率低於此值視為原地震盪
        false_breakout_threshold: 假突破次數高於此值視為絞肉

    Returns:
        ChopResult
    """
    if len(df) < lookback + 5:
        return ChopResult(is_chop=False, score=0.0, reasons=[], cooldown_minutes=0)

    score = 0.0
    reasons = []

    # 1. ADX 趨勢強度
    if "adx" in df.columns:
        adx = df["adx"].iloc[-1]
        if not pd.isna(adx) and adx < adx_threshold:
            score += 0.3
            reasons.append(f"ADX={adx:.1f} < {adx_threshold} (無趨勢)")

    # 2. 影線佔比
    wick = _wick_ratio(df, lookback)
    if wick > wick_threshold:
        score += 0.25
        reasons.append(f"影線佔比={wick:.2f} > {wick_threshold} (多空交戰)")

    # 3. 價格位移率
    displacement = _price_displacement(df, lookback)
    if displacement < displacement_threshold:
        score += 0.25
        reasons.append(f"位移率={displacement:.2f} < {displacement_threshold} (原地震盪)")

    # 4. 假突破
    fb_count = _false_breakout_count(df, lookback)
    if fb_count >= false_breakout_threshold:
        score += 0.2
        reasons.append(f"假突破={fb_count}次 >= {false_breakout_threshold} (頻繁掃止損)")

    score = min(score, 1.0)
    is_chop = score >= 0.6

    if is_chop:
        cooldown = 30 if score >= 0.75 else 15
    else:
        cooldown = 0

    if is_chop:
        logger.warning(f"Chop market detected! Score={score:.2f}, "
                       f"cooldown={cooldown}min, reasons: {reasons}")

    return ChopResult(
        is_chop=is_chop,
        score=round(score, 2),
        reasons=reasons,
        cooldown_minutes=cooldown,
    )


def get_chop_summary(df: pd.DataFrame) -> dict:
    """產生絞肉機偵測摘要"""
    result = detect_chop(df)
    return {
        "is_chop": result.is_chop,
        "score": result.score,
        "reasons": result.reasons,
        "cooldown_minutes": result.cooldown_minutes,
    }
