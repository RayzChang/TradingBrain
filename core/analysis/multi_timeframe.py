"""
多時間框架分析模組 (Multi-Timeframe Analysis, MTF)

核心原理:
  高時間框架 (HTF) 決定方向 → 低時間框架 (LTF) 決定進場

支援的 MTF 策略:
  1. 趨勢一致性檢查: 確認多個時間框架趨勢方向一致
  2. HTF 支撐/阻力 + LTF 進場信號
  3. MTF RSI 確認

時間框架層級:
  - 高: 4h, 1d
  - 中: 1h
  - 低: 15m, 5m (進場)
"""

from dataclasses import dataclass
from enum import Enum

import pandas as pd
from loguru import logger

from core.analysis.indicators import add_all_indicators, get_trend_direction


class TimeframeAlignment(str, Enum):
    ALIGNED_BULLISH = "aligned_bullish"
    ALIGNED_BEARISH = "aligned_bearish"
    CONFLICTING = "conflicting"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class MTFAnalysis:
    alignment: TimeframeAlignment
    details: dict[str, str]  # timeframe → trend direction
    confidence: float  # 0.0 ~ 1.0
    recommended_direction: str | None  # "LONG", "SHORT", None


# 時間框架排序（由高到低）
TF_HIERARCHY = ["1d", "4h", "1h", "15m", "5m"]


def analyze_multi_timeframe(
    kline_data: dict[str, pd.DataFrame],
    entry_tf: str = "15m",
) -> MTFAnalysis:
    """
    多時間框架趨勢分析。

    Args:
        kline_data: {timeframe: DataFrame} 字典，每個 DF 需要已有 OHLCV 欄位
        entry_tf: 進場用的時間框架

    Returns:
        MTFAnalysis 結果
    """
    details: dict[str, str] = {}
    trends: list[str] = []

    for tf in TF_HIERARCHY:
        if tf not in kline_data:
            continue
        df = kline_data[tf]
        if df.empty or len(df) < 50:
            details[tf] = "INSUFFICIENT"
            continue

        df_with_ind = add_all_indicators(df)
        trend = get_trend_direction(df_with_ind)
        details[tf] = trend
        trends.append(trend)

    if len(trends) < 2:
        return MTFAnalysis(
            alignment=TimeframeAlignment.INSUFFICIENT_DATA,
            details=details,
            confidence=0.0,
            recommended_direction=None,
        )

    bullish_count = trends.count("BULLISH")
    bearish_count = trends.count("BEARISH")
    total = len(trends)

    if bullish_count == total:
        return MTFAnalysis(
            alignment=TimeframeAlignment.ALIGNED_BULLISH,
            details=details,
            confidence=1.0,
            recommended_direction="LONG",
        )
    elif bearish_count == total:
        return MTFAnalysis(
            alignment=TimeframeAlignment.ALIGNED_BEARISH,
            details=details,
            confidence=1.0,
            recommended_direction="SHORT",
        )

    # 部分一致：以高時間框架為主
    htf_trends = []
    for tf in ["1d", "4h", "1h"]:
        if tf in details and details[tf] in ("BULLISH", "BEARISH"):
            htf_trends.append(details[tf])

    if not htf_trends:
        return MTFAnalysis(
            alignment=TimeframeAlignment.CONFLICTING,
            details=details,
            confidence=0.0,
            recommended_direction=None,
        )

    htf_bullish = htf_trends.count("BULLISH")
    htf_bearish = htf_trends.count("BEARISH")

    if htf_bullish > htf_bearish:
        direction = "LONG"
        confidence = htf_bullish / len(htf_trends) * (bullish_count / total)
    elif htf_bearish > htf_bullish:
        direction = "SHORT"
        confidence = htf_bearish / len(htf_trends) * (bearish_count / total)
    else:
        return MTFAnalysis(
            alignment=TimeframeAlignment.CONFLICTING,
            details=details,
            confidence=0.3,
            recommended_direction=None,
        )

    return MTFAnalysis(
        alignment=(
            TimeframeAlignment.ALIGNED_BULLISH if direction == "LONG"
            else TimeframeAlignment.ALIGNED_BEARISH
        ),
        details=details,
        confidence=round(confidence, 2),
        recommended_direction=direction,
    )


def check_htf_rsi_confirmation(
    kline_data: dict[str, pd.DataFrame],
    direction: str,
    htf_list: list[str] | None = None,
) -> bool:
    """
    確認高時間框架的 RSI 不處於極端區域（避免逆勢進場）。

    如果做多，確認 HTF RSI < 75（非超買）
    如果做空，確認 HTF RSI > 25（非超賣）
    """
    for tf in (htf_list or ["4h", "1h"]):
        if tf not in kline_data:
            continue
        df = kline_data[tf]
        if df.empty or "rsi" not in df.columns:
            df = add_all_indicators(df)

        rsi = df["rsi"].iloc[-1] if "rsi" in df.columns else None
        if rsi is None or pd.isna(rsi):
            continue

        if direction == "LONG" and rsi > 75:
            logger.info(f"HTF RSI confirmation failed: {tf} RSI={rsi:.1f} > 75 (overbought)")
            return False
        if direction == "SHORT" and rsi < 25:
            logger.info(f"HTF RSI confirmation failed: {tf} RSI={rsi:.1f} < 25 (oversold)")
            return False

    return True


def get_mtf_summary(kline_data: dict[str, pd.DataFrame]) -> dict:
    """產生 MTF 分析摘要"""
    analysis = analyze_multi_timeframe(kline_data)
    return {
        "alignment": analysis.alignment.value,
        "details": analysis.details,
        "confidence": analysis.confidence,
        "recommended_direction": analysis.recommended_direction,
    }
