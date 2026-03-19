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
DIRECTION_TFS = ["4h", "1h"]


def _normalize_direction(raw: str | None) -> tuple[str | None, float]:
    """Map raw trend labels into directional bias and confidence."""
    mapping = {
        "BULLISH": ("BULLISH", 1.0),
        "LEAN_BULLISH": ("BULLISH", 0.6),
        "BEARISH": ("BEARISH", 1.0),
        "LEAN_BEARISH": ("BEARISH", 0.6),
    }
    return mapping.get(raw, (None, 0.0))


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

    directional_details = {tf: details.get(tf) for tf in DIRECTION_TFS}
    if any(directional_details.get(tf) == "INSUFFICIENT" for tf in DIRECTION_TFS):
        return MTFAnalysis(
            alignment=TimeframeAlignment.INSUFFICIENT_DATA,
            details=details,
            confidence=0.0,
            recommended_direction=None,
        )

    dir_4h, conf_4h = _normalize_direction(directional_details.get("4h"))
    dir_1h, conf_1h = _normalize_direction(directional_details.get("1h"))

    if dir_4h is None and dir_1h is None:
        return MTFAnalysis(
            alignment=TimeframeAlignment.CONFLICTING,
            details=details,
            confidence=0.0,
            recommended_direction=None,
        )

    if dir_4h and dir_1h and dir_4h != dir_1h:
        return MTFAnalysis(
            alignment=TimeframeAlignment.CONFLICTING,
            details=details,
            confidence=0.0,
            recommended_direction=None,
        )

    agreed_dir = dir_4h or dir_1h
    confidence = min(conf_4h, conf_1h) if dir_4h and dir_1h else (conf_4h or conf_1h)

    if dir_4h is None or dir_1h is None:
        confidence *= 0.5

    return MTFAnalysis(
        alignment=(
            TimeframeAlignment.ALIGNED_BULLISH
            if agreed_dir == "BULLISH"
            else TimeframeAlignment.ALIGNED_BEARISH
        ),
        details=details,
        confidence=round(confidence, 2),
        recommended_direction="LONG" if agreed_dir == "BULLISH" else "SHORT",
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
