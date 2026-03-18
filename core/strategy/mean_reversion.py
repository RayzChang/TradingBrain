"""Mean reversion strategy with stricter reversal confirmation."""

import pandas as pd
from loguru import logger

from core.analysis.candlestick import PatternDirection
from core.analysis.engine import AnalysisResult
from core.strategy.base import BaseStrategy, MarketRegime, TradeSignal


class MeanReversionStrategy(BaseStrategy):
    """Fade stretched moves only when ranging conditions show a real reversal setup."""

    allowed_regimes = [MarketRegime.RANGING]

    def __init__(
        self,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        bb_touch_threshold: float = 0.02,
        skip_on_chop: bool = True,
        short_rsi_floor: float = 65.0,
        long_rsi_ceiling: float = 35.0,
    ) -> None:
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.bb_touch_threshold = bb_touch_threshold
        self.skip_on_chop = skip_on_chop
        self.short_rsi_floor = short_rsi_floor
        self.long_rsi_ceiling = long_rsi_ceiling

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

        if result.df_enriched is None or len(result.df_enriched) < 2:
            return signals

        if self.skip_on_chop and result.chop and result.chop.is_chop:
            return signals

        ind = result.indicators
        rsi = ind.get("rsi")
        bb_pct = ind.get("bb_pct")
        if rsi is None:
            return signals

        try:
            rsi_f = float(rsi)
        except (TypeError, ValueError):
            return signals

        prev = result.df_enriched.iloc[-2]
        curr = result.df_enriched.iloc[-1]
        close = curr.get("close")
        open_price = curr.get("open")
        bb_lower = curr.get("bb_lower")
        bb_upper = curr.get("bb_upper")
        prev_close = prev.get("close")

        if close is None or close <= 0 or open_price is None or prev_close is None:
            return signals

        candle_bonus = self._candle_pattern_bonus(result)
        fib_info = self._fibonacci_bonus(result, float(close))
        has_bull_div = any(
            divergence.type.value in ("regular_bullish", "hidden_bullish")
            for divergence in result.divergences
        )
        has_bear_div = any(
            divergence.type.value in ("regular_bearish", "hidden_bearish")
            for divergence in result.divergences
        )

        if bb_lower is not None and not pd.isna(bb_lower):
            dist_lower = (close - float(bb_lower)) / close
            bullish_reversal = bool(
                close > open_price
                and close >= prev_close
            )
            if dist_lower <= self.bb_touch_threshold and rsi_f <= self.long_rsi_ceiling:
                strength = 0.5 + (self.rsi_oversold - rsi_f) / 40.0
                strength = min(max(strength, 0.0), 1.0)

                if has_bull_div:
                    strength = min(strength + 0.15, 1.0)
                if candle_bonus.get("bullish", 0) > 0:
                    strength = min(strength + 0.1, 1.0)
                if fib_info.get("near_support", False):
                    strength = min(strength + 0.1, 1.0)
                if candle_bonus.get("bearish", 0) > 0:
                    strength = max(strength - 0.1, 0.0)

                if bullish_reversal and (has_bull_div or candle_bonus.get("bullish", 0) > 0):
                    signals.append(
                        TradeSignal(
                            symbol=symbol,
                            timeframe=timeframe,
                            signal_type="LONG",
                            strength=round(max(strength, 0.3), 2),
                            strategy_name=self.name,
                            indicators={
                                "rsi": round(rsi_f, 2),
                                "bb_pct": round(float(bb_pct), 4) if bb_pct is not None else None,
                                "close": round(float(close), 4),
                                "bb_lower": round(float(bb_lower), 4),
                                "divergence_bullish": has_bull_div,
                                "candle_bullish": candle_bonus.get("bullish", 0),
                                "fib_support": fib_info.get("near_support", False),
                                "bullish_reversal": bullish_reversal,
                            },
                            reason="Bollinger lower touch with RSI oversold and bullish reversal",
                        )
                    )
                    logger.debug(
                        f"{self.name} LONG signal: {symbol} {timeframe} "
                        f"RSI={rsi_f:.1f} strength={strength:.2f}"
                    )

        if bb_upper is not None and not pd.isna(bb_upper):
            dist_upper = (float(bb_upper) - close) / close
            bearish_reversal = bool(
                close < open_price
                and close <= prev_close
            )
            if dist_upper <= self.bb_touch_threshold and rsi_f >= self.short_rsi_floor:
                strength = 0.5 + (rsi_f - self.rsi_overbought) / 40.0
                strength = min(max(strength, 0.0), 1.0)

                if has_bear_div:
                    strength = min(strength + 0.15, 1.0)
                if candle_bonus.get("bearish", 0) > 0:
                    strength = min(strength + 0.1, 1.0)
                if fib_info.get("near_resistance", False):
                    strength = min(strength + 0.1, 1.0)
                if candle_bonus.get("bullish", 0) > 0:
                    strength = max(strength - 0.1, 0.0)

                if bearish_reversal and (has_bear_div or candle_bonus.get("bearish", 0) > 0):
                    signals.append(
                        TradeSignal(
                            symbol=symbol,
                            timeframe=timeframe,
                            signal_type="SHORT",
                            strength=round(max(strength, 0.3), 2),
                            strategy_name=self.name,
                            indicators={
                                "rsi": round(rsi_f, 2),
                                "bb_pct": round(float(bb_pct), 4) if bb_pct is not None else None,
                                "close": round(float(close), 4),
                                "bb_upper": round(float(bb_upper), 4),
                                "divergence_bearish": has_bear_div,
                                "candle_bearish": candle_bonus.get("bearish", 0),
                                "fib_resistance": fib_info.get("near_resistance", False),
                                "bearish_reversal": bearish_reversal,
                            },
                            reason="Bollinger upper touch with RSI overbought and bearish reversal",
                        )
                    )
                    logger.debug(
                        f"{self.name} SHORT signal: {symbol} {timeframe} "
                        f"RSI={rsi_f:.1f} strength={strength:.2f}"
                    )

        return signals

    @staticmethod
    def _candle_pattern_bonus(result: AnalysisResult) -> dict:
        bullish_count = 0
        bearish_count = 0
        for pattern in result.candle_patterns:
            if pattern.direction == PatternDirection.BULLISH:
                bullish_count += 1
            elif pattern.direction == PatternDirection.BEARISH:
                bearish_count += 1
        return {"bullish": bullish_count, "bearish": bearish_count}

    @staticmethod
    def _fibonacci_bonus(result: AnalysisResult, current_price: float) -> dict:
        fib = result.fibonacci
        if not fib or not fib.get("available"):
            return {"near_support": False, "near_resistance": False}

        near_support = False
        near_resistance = False

        support = fib.get("nearest_support")
        resistance = fib.get("nearest_resistance")

        if support and current_price > 0:
            support_price = support.get("price", 0)
            if abs(current_price - support_price) / current_price < 0.01:
                near_support = True

        if resistance and current_price > 0:
            resistance_price = resistance.get("price", 0)
            if abs(resistance_price - current_price) / current_price < 0.01:
                near_resistance = True

        return {"near_support": near_support, "near_resistance": near_resistance}
