"""
趨勢跟蹤策略 (Trend Following)

邏輯:
- 做多: EMA9 上穿 EMA21，且 ADX > 門檻（確認有趨勢）
- 做空: EMA9 下穿 EMA21，且 ADX > 門檻
- 僅在非絞肉機行情下出信號（chop 由否決引擎處理，此處可選過濾）
"""

import pandas as pd
from loguru import logger

from core.analysis.engine import AnalysisResult
from core.strategy.base import BaseStrategy, TradeSignal


class TrendFollowingStrategy(BaseStrategy):
    """
    EMA 交叉 + ADX 趨勢強度確認。
    """

    def __init__(
        self,
        adx_min: float = 25.0,
        skip_on_chop: bool = True,
    ) -> None:
        self.adx_min = adx_min
        self.skip_on_chop = skip_on_chop

    @property
    def name(self) -> str:
        return "trend_following"

    def evaluate_single(
        self,
        symbol: str,
        timeframe: str,
        result: AnalysisResult,
    ) -> list[TradeSignal]:
        signals: list[TradeSignal] = []

        if result.df_enriched is None or len(result.df_enriched) < 3:
            return signals

        if self.skip_on_chop and result.chop and result.chop.is_chop:
            return signals

        df = result.df_enriched
        if "ema_9" not in df.columns or "ema_21" not in df.columns or "adx" not in df.columns:
            return signals

        # 最近兩根 K 線
        prev = df.iloc[-2]
        curr = df.iloc[-1]

        adx = curr.get("adx")
        if adx is None or (isinstance(adx, float) and (adx < self.adx_min or pd.isna(adx))):
            return signals

        ema9_prev = prev.get("ema_9")
        ema21_prev = prev.get("ema_21")
        ema9_curr = curr.get("ema_9")
        ema21_curr = curr.get("ema_21")

        if any(v is None or (isinstance(v, float) and pd.isna(v)) for v in (ema9_prev, ema21_prev, ema9_curr, ema21_curr)):
            return signals

        # 金叉：前一根 EMA9 <= EMA21，當前 EMA9 > EMA21
        if ema9_prev <= ema21_prev and ema9_curr > ema21_curr:
            strength = min(0.5 + (adx - self.adx_min) / 50.0, 1.0)
            strength = max(0.0, strength)
            signals.append(TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type="LONG",
                strength=round(strength, 2),
                strategy_name=self.name,
                indicators={
                    "trend": result.indicators.get("trend", ""),
                    "adx": round(float(adx), 2),
                    "ema_9": round(float(ema9_curr), 4),
                    "ema_21": round(float(ema21_curr), 4),
                },
                reason="EMA9 上穿 EMA21，ADX 確認趨勢",
            ))
            logger.debug(f"{self.name} LONG signal: {symbol} {timeframe} ADX={adx:.1f}")

        # 死叉：前一根 EMA9 >= EMA21，當前 EMA9 < EMA21
        if ema9_prev >= ema21_prev and ema9_curr < ema21_curr:
            strength = min(0.5 + (adx - self.adx_min) / 50.0, 1.0)
            strength = max(0.0, strength)
            signals.append(TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type="SHORT",
                strength=round(strength, 2),
                strategy_name=self.name,
                indicators={
                    "trend": result.indicators.get("trend", ""),
                    "adx": round(float(adx), 2),
                    "ema_9": round(float(ema9_curr), 4),
                    "ema_21": round(float(ema21_curr), 4),
                },
                reason="EMA9 下穿 EMA21，ADX 確認趨勢",
            ))
            logger.debug(f"{self.name} SHORT signal: {symbol} {timeframe} ADX={adx:.1f}")

        return signals
