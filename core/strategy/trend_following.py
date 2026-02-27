"""
趨勢跟蹤策略 (Trend Following) v2

邏輯:
- 做多: EMA9 上穿 EMA21，且 ADX > 門檻（確認有趨勢）
- 做空: EMA9 下穿 EMA21，且 ADX > 門檻
- 僅在非絞肉機行情下出信號

v2 改版：
  - 整合 K 線型態確認（看漲型態加分做多、看跌型態加分做空）
  - 整合斐波那契作為進場優化（在 fib 支撐位附近做多加分）
  - 整合背離作為額外確認
"""

import pandas as pd
from loguru import logger

from core.analysis.engine import AnalysisResult
from core.analysis.candlestick import PatternDirection
from core.strategy.base import BaseStrategy, TradeSignal, MarketRegime


class TrendFollowingStrategy(BaseStrategy):
    """
    EMA 交叉 + ADX 趨勢強度確認 + K 線型態 + 斐波那契。
    只在趨勢狀態 (ADX >= 20) 下出信號。
    """
    allowed_regimes = [MarketRegime.TRENDING]

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

        # --- 預計算確認因子 ---
        candle_bonus = self._candle_pattern_bonus(result)
        fib_info = self._fibonacci_bonus(result, float(curr.get("close", 0)))
        divergence_bonus = self._divergence_bonus(result)

        # 金叉：前一根 EMA9 <= EMA21，當前 EMA9 > EMA21
        if ema9_prev <= ema21_prev and ema9_curr > ema21_curr:
            strength = min(0.5 + (adx - self.adx_min) / 50.0, 1.0)
            strength = max(0.0, strength)

            # K 線型態加分
            if candle_bonus.get("bullish", 0) > 0:
                strength = min(strength + 0.1, 1.0)
            # 斐波那契支撐加分
            if fib_info.get("near_support", False):
                strength = min(strength + 0.1, 1.0)
            # 看漲背離加分
            if divergence_bonus.get("bullish", False):
                strength = min(strength + 0.1, 1.0)
            # 看跌型態扣分（不利於做多）
            if candle_bonus.get("bearish", 0) > 0:
                strength = max(strength - 0.15, 0.0)

            if strength >= 0.3:  # 最低門檻
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
                        "candle_confirm": candle_bonus,
                        "fib_support": fib_info.get("near_support", False),
                        "divergence_bullish": divergence_bonus.get("bullish", False),
                    },
                    reason="EMA9 上穿 EMA21，ADX 確認趨勢" + self._build_reason_suffix(candle_bonus, fib_info, divergence_bonus, "LONG"),
                ))
                logger.debug(f"{self.name} LONG signal: {symbol} {timeframe} ADX={adx:.1f} strength={strength:.2f}")

        # 死叉：前一根 EMA9 >= EMA21，當前 EMA9 < EMA21
        if ema9_prev >= ema21_prev and ema9_curr < ema21_curr:
            strength = min(0.5 + (adx - self.adx_min) / 50.0, 1.0)
            strength = max(0.0, strength)

            # K 線型態加分
            if candle_bonus.get("bearish", 0) > 0:
                strength = min(strength + 0.1, 1.0)
            # 斐波那契阻力加分
            if fib_info.get("near_resistance", False):
                strength = min(strength + 0.1, 1.0)
            # 看跌背離加分
            if divergence_bonus.get("bearish", False):
                strength = min(strength + 0.1, 1.0)
            # 看漲型態扣分（不利於做空）
            if candle_bonus.get("bullish", 0) > 0:
                strength = max(strength - 0.15, 0.0)

            if strength >= 0.3:
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
                        "candle_confirm": candle_bonus,
                        "fib_resistance": fib_info.get("near_resistance", False),
                        "divergence_bearish": divergence_bonus.get("bearish", False),
                    },
                    reason="EMA9 下穿 EMA21，ADX 確認趨勢" + self._build_reason_suffix(candle_bonus, fib_info, divergence_bonus, "SHORT"),
                ))
                logger.debug(f"{self.name} SHORT signal: {symbol} {timeframe} ADX={adx:.1f} strength={strength:.2f}")

        return signals

    @staticmethod
    def _candle_pattern_bonus(result: AnalysisResult) -> dict:
        """計算 K 線型態對信號的加分"""
        bullish_count = 0
        bearish_count = 0
        for p in result.candle_patterns:
            if p.direction == PatternDirection.BULLISH:
                bullish_count += 1
            elif p.direction == PatternDirection.BEARISH:
                bearish_count += 1
        return {"bullish": bullish_count, "bearish": bearish_count}

    @staticmethod
    def _fibonacci_bonus(result: AnalysisResult, current_price: float) -> dict:
        """計算斐波那契對信號的加分"""
        fib = result.fibonacci
        if not fib or not fib.get("available"):
            return {"near_support": False, "near_resistance": False}

        near_support = False
        near_resistance = False

        support = fib.get("nearest_support")
        resistance = fib.get("nearest_resistance")

        if support and current_price > 0:
            support_price = support.get("price", 0)
            dist = abs(current_price - support_price) / current_price
            if dist < 0.01:  # 價格距離支撐位 < 1%
                near_support = True

        if resistance and current_price > 0:
            resistance_price = resistance.get("price", 0)
            dist = abs(resistance_price - current_price) / current_price
            if dist < 0.01:
                near_resistance = True

        return {"near_support": near_support, "near_resistance": near_resistance}

    @staticmethod
    def _divergence_bonus(result: AnalysisResult) -> dict:
        """計算背離對信號的加分"""
        bullish = any(d.type.value in ("regular_bullish", "hidden_bullish") for d in result.divergences)
        bearish = any(d.type.value in ("regular_bearish", "hidden_bearish") for d in result.divergences)
        return {"bullish": bullish, "bearish": bearish}

    @staticmethod
    def _build_reason_suffix(candle: dict, fib: dict, div: dict, direction: str) -> str:
        parts = []
        if direction == "LONG":
            if candle.get("bullish", 0) > 0:
                parts.append("看漲型態確認")
            if fib.get("near_support", False):
                parts.append("斐波那契支撐位")
            if div.get("bullish", False):
                parts.append("看漲背離")
        else:
            if candle.get("bearish", 0) > 0:
                parts.append("看跌型態確認")
            if fib.get("near_resistance", False):
                parts.append("斐波那契阻力位")
            if div.get("bearish", False):
                parts.append("看跌背離")
        if parts:
            return "（" + "、".join(parts) + "）"
        return ""
