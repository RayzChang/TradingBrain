"""
均值回歸策略 (Mean Reversion) v2

邏輯:
- 做多: 價格觸及或跌破布林下軌，且 RSI 超賣 (< 30)
- 做空: 價格觸及或突破布林上軌，且 RSI 超買 (> 70)
- 可選: 背離輔助（有看漲背離時做多信號加分）

v2 改版：
  - 整合 K 線型態確認（錘子線、吞噬等加分）
  - 整合斐波那契支撐/阻力位確認
  - 增加最低信心門檻（避免弱信號通過）
"""

import pandas as pd
from loguru import logger

from core.analysis.engine import AnalysisResult
from core.analysis.candlestick import PatternDirection
from core.strategy.base import BaseStrategy, TradeSignal, MarketRegime


class MeanReversionStrategy(BaseStrategy):
    """
    布林帶 + RSI 超買超賣 + K 線型態 + 斐波那契。
    只在震盪狀態 (ADX < 20) 下出信號，避免逆勢操作。
    """
    allowed_regimes = [MarketRegime.RANGING]

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

        # --- 預計算確認因子 ---
        candle_bonus = self._candle_pattern_bonus(result)
        fib_info = self._fibonacci_bonus(result, float(close))

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

                # K 線型態加分（如錘子線、晨星、看漲吞噬）
                if candle_bonus.get("bullish", 0) > 0:
                    strength = min(strength + 0.1, 1.0)

                # 斐波那契支撐加分
                if fib_info.get("near_support", False):
                    strength = min(strength + 0.1, 1.0)

                # 看跌型態扣分
                if candle_bonus.get("bearish", 0) > 0:
                    strength = max(strength - 0.1, 0.0)

                reason_parts = ["觸及布林下軌且 RSI 超賣"]
                if has_bull_div:
                    reason_parts.append("看漲背離")
                if candle_bonus.get("bullish", 0) > 0:
                    reason_parts.append("看漲型態確認")
                if fib_info.get("near_support", False):
                    reason_parts.append("斐波那契支撐位")

                if strength >= 0.3:  # 最低門檻
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
                            "candle_bullish": candle_bonus.get("bullish", 0),
                            "fib_support": fib_info.get("near_support", False),
                        },
                        reason="（".join(reason_parts[:1]) + ("（" + "、".join(reason_parts[1:]) + "）" if len(reason_parts) > 1 else ""),
                    ))
                    logger.debug(f"{self.name} LONG signal: {symbol} {timeframe} RSI={rsi_f:.1f} strength={strength:.2f}")

        # 做空：價格接近上軌 + RSI 超買
        if bb_upper is not None and not pd.isna(bb_upper):
            dist_upper = (float(bb_upper) - close) / close
            if dist_upper <= self.bb_touch_threshold and rsi_f > self.rsi_overbought:
                strength = 0.5 + (rsi_f - self.rsi_overbought) / 50.0
                strength = min(max(strength, 0.0), 1.0)

                has_bear_div = any(d.type.value == "regular_bearish" for d in result.divergences)
                if has_bear_div:
                    strength = min(strength + 0.15, 1.0)

                if candle_bonus.get("bearish", 0) > 0:
                    strength = min(strength + 0.1, 1.0)

                if fib_info.get("near_resistance", False):
                    strength = min(strength + 0.1, 1.0)

                if candle_bonus.get("bullish", 0) > 0:
                    strength = max(strength - 0.1, 0.0)

                reason_parts = ["觸及布林上軌且 RSI 超買"]
                if has_bear_div:
                    reason_parts.append("看跌背離")
                if candle_bonus.get("bearish", 0) > 0:
                    reason_parts.append("看跌型態確認")
                if fib_info.get("near_resistance", False):
                    reason_parts.append("斐波那契阻力位")

                if strength >= 0.3:
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
                            "candle_bearish": candle_bonus.get("bearish", 0),
                            "fib_resistance": fib_info.get("near_resistance", False),
                        },
                        reason="（".join(reason_parts[:1]) + ("（" + "、".join(reason_parts[1:]) + "）" if len(reason_parts) > 1 else ""),
                    ))
                    logger.debug(f"{self.name} SHORT signal: {symbol} {timeframe} RSI={rsi_f:.1f} strength={strength:.2f}")

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
            if dist < 0.01:
                near_support = True

        if resistance and current_price > 0:
            resistance_price = resistance.get("price", 0)
            dist = abs(resistance_price - current_price) / current_price
            if dist < 0.01:
                near_resistance = True

        return {"near_support": near_support, "near_resistance": near_resistance}
