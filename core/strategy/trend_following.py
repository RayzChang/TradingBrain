"""Trend following strategy with stricter long-side confirmation."""

import pandas as pd
from loguru import logger

from core.analysis.candlestick import PatternDirection
from core.analysis.engine import AnalysisResult
from core.strategy.base import BaseStrategy, MarketRegime, TradeSignal


class TrendFollowingStrategy(BaseStrategy):
    """Trade confirmed EMA crossovers in trending conditions."""

    allowed_regimes = [MarketRegime.TRENDING]

    def __init__(
        self,
        adx_min: float = 25.0,
        skip_on_chop: bool = True,
        long_rsi_floor: float = 52.0,
        long_rsi_ceiling: float = 68.0,
        short_rsi_floor: float = 32.0,
        short_rsi_ceiling: float = 48.0,
    ) -> None:
        self.adx_min = adx_min
        self.skip_on_chop = skip_on_chop
        self.require_bullish_trend_stack = True
        self.long_rsi_floor = long_rsi_floor
        self.long_rsi_ceiling = long_rsi_ceiling
        self.short_rsi_floor = short_rsi_floor
        self.short_rsi_ceiling = short_rsi_ceiling

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
        required = {"ema_9", "ema_21", "adx"}
        if not required.issubset(df.columns):
            return signals

        prev = df.iloc[-2]
        curr = df.iloc[-1]

        adx = curr.get("adx")
        if adx is None or (isinstance(adx, float) and (adx < self.adx_min or pd.isna(adx))):
            return signals

        ema9_prev = prev.get("ema_9")
        ema21_prev = prev.get("ema_21")
        ema9_curr = curr.get("ema_9")
        ema21_curr = curr.get("ema_21")
        ema50_prev = prev.get("ema_50")
        ema50_curr = curr.get("ema_50")
        adx_pos_curr = curr.get("adx_pos")
        adx_neg_curr = curr.get("adx_neg")
        close_curr = curr.get("close")
        prev_high = prev.get("high")
        rsi_curr = curr.get("rsi")
        macd_hist_curr = curr.get("macd_hist")
        macd_hist_prev = prev.get("macd_hist")

        if any(
            value is None or (isinstance(value, float) and pd.isna(value))
            for value in (ema9_prev, ema21_prev, ema9_curr, ema21_curr)
        ):
            return signals

        candle_bonus = self._candle_pattern_bonus(result)
        fib_info = self._fibonacci_bonus(result, float(curr.get("close", 0)))
        divergence_bonus = self._divergence_bonus(result)
        bullish_confluence = int(candle_bonus.get("bullish", 0) > 0) + int(
            fib_info.get("near_support", False)
        ) + int(divergence_bonus.get("bullish", False))
        bearish_confluence = int(candle_bonus.get("bearish", 0) > 0) + int(
            fib_info.get("near_resistance", False)
        ) + int(divergence_bonus.get("bearish", False))

        if ema9_prev <= ema21_prev and ema9_curr > ema21_curr:
            bullish_stack_ok = True
            bullish_di_ok = True
            bullish_momentum_ok = True

            if self.require_bullish_trend_stack:
                bullish_stack_values = (
                    ema50_prev,
                    ema50_curr,
                    adx_pos_curr,
                    adx_neg_curr,
                    close_curr,
                    prev_high,
                    rsi_curr,
                    macd_hist_curr,
                    macd_hist_prev,
                )
                if any(
                    value is None or (isinstance(value, float) and pd.isna(value))
                    for value in bullish_stack_values
                ):
                    bullish_stack_ok = False
                    bullish_di_ok = False
                    bullish_momentum_ok = False
                else:
                    bullish_stack_ok = bool(
                        ema21_curr > ema50_curr
                        and ema50_curr >= ema50_prev
                        and close_curr > ema50_curr
                        and ema9_curr > ema50_curr
                    )
                    bullish_di_ok = bool(adx_pos_curr > adx_neg_curr)
                    bullish_momentum_ok = bool(
                        self.long_rsi_floor <= rsi_curr <= self.long_rsi_ceiling
                        and macd_hist_curr > 0
                        and macd_hist_curr >= macd_hist_prev
                        and close_curr > prev_high
                    )

            if (
                not bullish_stack_ok
                or not bullish_di_ok
                or not bullish_momentum_ok
                or bullish_confluence < 1
            ):
                logger.debug(
                    f"{self.name} LONG filtered: {symbol} {timeframe} "
                    f"stack={bullish_stack_ok} di={bullish_di_ok} "
                    f"momentum={bullish_momentum_ok} confluence={bullish_confluence}"
                )
                return signals

            strength = min(0.5 + (adx - self.adx_min) / 50.0, 1.0)
            strength = max(0.0, strength)

            if candle_bonus.get("bullish", 0) > 0:
                strength = min(strength + 0.1, 1.0)
            if fib_info.get("near_support", False):
                strength = min(strength + 0.1, 1.0)
            if divergence_bonus.get("bullish", False):
                strength = min(strength + 0.1, 1.0)
            if candle_bonus.get("bearish", 0) > 0:
                strength = max(strength - 0.15, 0.0)

            if strength >= 0.3:
                signals.append(
                    TradeSignal(
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
                            "ema_50": round(float(ema50_curr), 4) if ema50_curr is not None else None,
                            "adx_pos": round(float(adx_pos_curr), 2) if adx_pos_curr is not None else None,
                            "adx_neg": round(float(adx_neg_curr), 2) if adx_neg_curr is not None else None,
                            "rsi": round(float(rsi_curr), 2) if rsi_curr is not None else None,
                            "macd_hist": round(float(macd_hist_curr), 4) if macd_hist_curr is not None else None,
                            "bullish_stack_ok": bullish_stack_ok,
                            "bullish_momentum_ok": bullish_momentum_ok,
                            "candle_confirm": candle_bonus,
                            "fib_support": fib_info.get("near_support", False),
                            "divergence_bullish": divergence_bonus.get("bullish", False),
                        },
                        reason=(
                            "EMA9 crossed above EMA21 with bullish trend stack"
                            + self._build_reason_suffix(candle_bonus, fib_info, divergence_bonus, "LONG")
                        ),
                    )
                )
                logger.debug(f"{self.name} LONG signal: {symbol} {timeframe} ADX={adx:.1f} strength={strength:.2f}")

        if ema9_prev >= ema21_prev and ema9_curr < ema21_curr:
            bearish_stack_values = (
                ema50_prev,
                ema50_curr,
                adx_pos_curr,
                adx_neg_curr,
                close_curr,
                prev.get("low"),
                rsi_curr,
                macd_hist_curr,
                macd_hist_prev,
            )
            if any(
                value is None or (isinstance(value, float) and pd.isna(value))
                for value in bearish_stack_values
            ):
                return signals

            bearish_stack_ok = bool(
                ema21_curr < ema50_curr
                and ema50_curr <= ema50_prev
                and close_curr < ema50_curr
                and ema9_curr < ema50_curr
            )
            bearish_di_ok = bool(adx_neg_curr > adx_pos_curr)
            bearish_momentum_ok = bool(
                self.short_rsi_floor <= rsi_curr <= self.short_rsi_ceiling
                and macd_hist_curr < 0
                and macd_hist_curr <= macd_hist_prev
                and close_curr < prev.get("low")
            )

            if (
                not bearish_stack_ok
                or not bearish_di_ok
                or not bearish_momentum_ok
                or bearish_confluence < 1
            ):
                logger.debug(
                    f"{self.name} SHORT filtered: {symbol} {timeframe} "
                    f"stack={bearish_stack_ok} di={bearish_di_ok} "
                    f"momentum={bearish_momentum_ok} confluence={bearish_confluence}"
                )
                return signals

            strength = min(0.5 + (adx - self.adx_min) / 50.0, 1.0)
            strength = max(0.0, strength)

            if candle_bonus.get("bearish", 0) > 0:
                strength = min(strength + 0.1, 1.0)
            if fib_info.get("near_resistance", False):
                strength = min(strength + 0.1, 1.0)
            if divergence_bonus.get("bearish", False):
                strength = min(strength + 0.1, 1.0)
            if candle_bonus.get("bullish", 0) > 0:
                strength = max(strength - 0.15, 0.0)

            if strength >= 0.3:
                signals.append(
                    TradeSignal(
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
                            "ema_50": round(float(ema50_curr), 4) if ema50_curr is not None else None,
                            "adx_pos": round(float(adx_pos_curr), 2) if adx_pos_curr is not None else None,
                            "adx_neg": round(float(adx_neg_curr), 2) if adx_neg_curr is not None else None,
                            "rsi": round(float(rsi_curr), 2) if rsi_curr is not None else None,
                            "macd_hist": round(float(macd_hist_curr), 4) if macd_hist_curr is not None else None,
                            "bearish_stack_ok": bearish_stack_ok,
                            "bearish_momentum_ok": bearish_momentum_ok,
                            "candle_confirm": candle_bonus,
                            "fib_resistance": fib_info.get("near_resistance", False),
                            "divergence_bearish": divergence_bonus.get("bearish", False),
                        },
                        reason=(
                            "EMA9 crossed below EMA21 with bearish trend stack"
                            + self._build_reason_suffix(candle_bonus, fib_info, divergence_bonus, "SHORT")
                        ),
                    )
                )
                logger.debug(f"{self.name} SHORT signal: {symbol} {timeframe} ADX={adx:.1f} strength={strength:.2f}")

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

    @staticmethod
    def _divergence_bonus(result: AnalysisResult) -> dict:
        bullish = any(
            divergence.type.value in ("regular_bullish", "hidden_bullish")
            for divergence in result.divergences
        )
        bearish = any(
            divergence.type.value in ("regular_bearish", "hidden_bearish")
            for divergence in result.divergences
        )
        return {"bullish": bullish, "bearish": bearish}

    @staticmethod
    def _build_reason_suffix(candle: dict, fib: dict, div: dict, direction: str) -> str:
        parts = []
        if direction == "LONG":
            if candle.get("bullish", 0) > 0:
                parts.append("bullish candle confirmation")
            if fib.get("near_support", False):
                parts.append("near support")
            if div.get("bullish", False):
                parts.append("bullish divergence")
        else:
            if candle.get("bearish", 0) > 0:
                parts.append("bearish candle confirmation")
            if fib.get("near_resistance", False):
                parts.append("near resistance")
            if div.get("bearish", False):
                parts.append("bearish divergence")
        return f" ({', '.join(parts)})" if parts else ""
