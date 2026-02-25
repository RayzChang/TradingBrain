"""
均值回歸策略 (Mean Reversion)

邏輯:
- 做多: 價格觸及或跌破布林下軌，且 RSI 超賣 (< 30)
- 做空: 價格觸及或突破布林上軌，且 RSI 超買 (> 70)
- 可選: 背離輔助（有看漲背離時做多信號加分）
"""

import pandas as pd
from loguru import logger

from core.analysis.engine import AnalysisResult
from core.strategy.base import BaseStrategy, TradeSignal


class MeanReversionStrategy(BaseStrategy):
    """
    布林帶 + RSI 超買超賣。
    """

    def __init__(
        self,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        bb_touch_threshold: float = 0.02,  # 價格與軌道距離在 2% 內視為觸及
        skip_on_chop: bool = True,
    ) -> None:
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.bb_touch_threshold = bb_touch_threshold
        self.skip_on_chop = skip_on_chop

    @property
    def name(self) -> str:
        return "mean_reversion"

    def evaluate_single(
        self,
        symbol: str,
        timeframe: str,
        result: AnalysisResult,
    ) -> list[TradeSignal]:
        signals: list[TradeSignal] = []

        if result.df_enriched is None or len(result.df_enriched) < 1:
            return signals

        if self.skip_on_chop and result.chop and result.chop.is_chop:
            return signals

        ind = result.indicators
        rsi = ind.get("rsi")
        bb_pct = ind.get("bb_pct")  # 0 = 下軌, 0.5 = 中軌, 1 = 上軌

        if rsi is None:
            return signals

        try:
            rsi_f = float(rsi)
        except (TypeError, ValueError):
            return signals

        curr = result.df_enriched.iloc[-1]
        close = curr.get("close")
        bb_lower = curr.get("bb_lower")
        bb_upper = curr.get("bb_upper")

        if close is None or close <= 0:
            return signals

        # 做多：價格接近下軌 + RSI 超賣
        if bb_lower is not None and not pd.isna(bb_lower):
            dist_lower = (close - float(bb_lower)) / close
            if dist_lower <= self.bb_touch_threshold and rsi_f < self.rsi_oversold:
                strength = 0.5 + (self.rsi_oversold - rsi_f) / 50.0
                strength = min(max(strength, 0.0), 1.0)
                # 背離加分
                has_bull_div = any(d.type.value == "regular_bullish" for d in result.divergences)
                if has_bull_div:
                    strength = min(strength + 0.15, 1.0)
                signals.append(TradeSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    signal_type="LONG",
                    strength=round(strength, 2),
                    strategy_name=self.name,
                    indicators={
                        "rsi": round(rsi_f, 2),
                        "bb_pct": round(float(bb_pct), 4) if bb_pct is not None else None,
                        "close": round(float(close), 4),
                        "bb_lower": round(float(bb_lower), 4),
                        "divergence_bullish": has_bull_div,
                    },
                    reason="觸及布林下軌且 RSI 超賣",
                ))
                logger.debug(f"{self.name} LONG signal: {symbol} {timeframe} RSI={rsi_f:.1f}")

        # 做空：價格接近上軌 + RSI 超買
        if bb_upper is not None and not pd.isna(bb_upper):
            dist_upper = (float(bb_upper) - close) / close
            if dist_upper <= self.bb_touch_threshold and rsi_f > self.rsi_overbought:
                strength = 0.5 + (rsi_f - self.rsi_overbought) / 50.0
                strength = min(max(strength, 0.0), 1.0)
                has_bear_div = any(d.type.value == "regular_bearish" for d in result.divergences)
                if has_bear_div:
                    strength = min(strength + 0.15, 1.0)
                signals.append(TradeSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    signal_type="SHORT",
                    strength=round(strength, 2),
                    strategy_name=self.name,
                    indicators={
                        "rsi": round(rsi_f, 2),
                        "bb_pct": round(float(bb_pct), 4) if bb_pct is not None else None,
                        "close": round(float(close), 4),
                        "bb_upper": round(float(bb_upper), 4),
                        "divergence_bearish": has_bear_div,
                    },
                    reason="觸及布林上軌且 RSI 超買",
                ))
                logger.debug(f"{self.name} SHORT signal: {symbol} {timeframe} RSI={rsi_f:.1f}")

        return signals
