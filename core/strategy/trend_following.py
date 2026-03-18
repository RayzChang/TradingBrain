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
        long_bb_position_ceiling: float = 0.85,
        long_rsi_quality_ceiling: float = 63.0,
        long_rsi_bb_position_ceiling: float = 0.75,
        short_bb_position_floor: float = 0.15,
        short_rsi_quality_floor: float = 37.0,
        short_rsi_bb_position_floor: float = 0.25,
        max_cross_age_bars: int = 30,
    ) -> None:
        self.adx_min = adx_min
        self.skip_on_chop = skip_on_chop
        self.require_bullish_trend_stack = True
        self.long_rsi_floor = long_rsi_floor
        self.long_rsi_ceiling = long_rsi_ceiling
        self.short_rsi_floor = short_rsi_floor
        self.short_rsi_ceiling = short_rsi_ceiling
        self.long_bb_position_ceiling = long_bb_position_ceiling
        self.long_rsi_quality_ceiling = long_rsi_quality_ceiling
        self.long_rsi_bb_position_ceiling = long_rsi_bb_position_ceiling
        self.short_bb_position_floor = short_bb_position_floor
        self.short_rsi_quality_floor = short_rsi_quality_floor
        self.short_rsi_bb_position_floor = short_rsi_bb_position_floor
        self.max_cross_age_bars = max_cross_age_bars

    @property
    def name(self) -> str:
        return "trend_following"

    def _get_bb_position(self, curr: pd.Series) -> float | None:
        bb_pct = curr.get("bb_pct")
        if bb_pct is not None and not (isinstance(bb_pct, float) and pd.isna(bb_pct)):
            return float(bb_pct)

        close = curr.get("close")
        bb_upper = curr.get("bb_upper")
        bb_lower = curr.get("bb_lower")
        values = (close, bb_upper, bb_lower)
        if any(value is None or (isinstance(value, float) and pd.isna(value)) for value in values):
            return None

        band_range = float(bb_upper) - float(bb_lower)
        if band_range <= 0:
            return None
        return (float(close) - float(bb_lower)) / band_range

    def _get_cross_age_bars(self, df: pd.DataFrame, bullish: bool) -> int | None:
        for idx in range(len(df) - 1, 0, -1):
            prev = df.iloc[idx - 1]
            curr = df.iloc[idx]
            prev_ema9 = prev.get("ema_9")
            prev_ema21 = prev.get("ema_21")
            curr_ema9 = curr.get("ema_9")
            curr_ema21 = curr.get("ema_21")
            values = (prev_ema9, prev_ema21, curr_ema9, curr_ema21)
            if any(value is None or (isinstance(value, float) and pd.isna(value)) for value in values):
                continue

            if bullish and prev_ema9 <= prev_ema21 and curr_ema9 > curr_ema21:
                return len(df) - 1 - idx
            if not bullish and prev_ema9 >= prev_ema21 and curr_ema9 < curr_ema21:
                return len(df) - 1 - idx
        return None

    def _log_entry_quality_filter(self, symbol: str, reason: str) -> None:
        logger.info(f"ENTRY_QUALITY_FILTER: {symbol} {reason}")

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
        bb_position = self._get_bb_position(curr)

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
        bullish_cross_age = self._get_cross_age_bars(df, bullish=True)
        bearish_cross_age = self._get_cross_age_bars(df, bullish=False)

        if ema9_curr > ema21_curr and bullish_cross_age is not None and bullish_cross_age <= 5:
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

            if bb_position is not None and bb_position > self.long_bb_position_ceiling:
                self._log_entry_quality_filter(
                    symbol,
                    f"LONG_bb_position_{bb_position:.2f}_above_{self.long_bb_position_ceiling:.2f}",
                )
                return signals
            if (
                rsi_curr is not None
                and bb_position is not None
                and rsi_curr > self.long_rsi_quality_ceiling
                and bb_position > self.long_rsi_bb_position_ceiling
            ):
                self._log_entry_quality_filter(
                    symbol,
                    (
                        f"LONG_rsi_{float(rsi_curr):.2f}_and_bb_position_{bb_position:.2f}"
                        f"_above_{self.long_rsi_bb_position_ceiling:.2f}"
                    ),
                )
                return signals
            if bullish_cross_age is not None and bullish_cross_age > self.max_cross_age_bars:
                self._log_entry_quality_filter(
                    symbol,
                    f"LONG_cross_age_{bullish_cross_age}_bars_above_{self.max_cross_age_bars}",
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
                breakout_momentum_bonus = (
                    prev_high is not None
                    and not (isinstance(prev_high, float) and pd.isna(prev_high))
                    and close_curr > prev_high
                )
                if breakout_momentum_bonus:
                    strength = min(strength + 0.1, 1.0)
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
                            "bb_position": round(float(bb_position), 4) if bb_position is not None else None,
                            "cross_age_bars": bullish_cross_age,
                            "breakout_momentum_bonus": breakout_momentum_bonus,
                            "entry_quality_filter_triggered": False,
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

        if ema9_curr < ema21_curr and bearish_cross_age is not None and bearish_cross_age <= 5:
            bearish_stack_values = (
                ema50_prev,
                ema50_curr,
                adx_pos_curr,
                adx_neg_curr,
                close_curr,
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

            if bb_position is not None and bb_position < self.short_bb_position_floor:
                self._log_entry_quality_filter(
                    symbol,
                    f"SHORT_bb_position_{bb_position:.2f}_below_{self.short_bb_position_floor:.2f}",
                )
                return signals
            if (
                rsi_curr is not None
                and bb_position is not None
                and rsi_curr < self.short_rsi_quality_floor
                and bb_position < self.short_rsi_bb_position_floor
            ):
                self._log_entry_quality_filter(
                    symbol,
                    (
                        f"SHORT_rsi_{float(rsi_curr):.2f}_and_bb_position_{bb_position:.2f}"
                        f"_below_{self.short_rsi_bb_position_floor:.2f}"
                    ),
                )
                return signals
            if bearish_cross_age is not None and bearish_cross_age > self.max_cross_age_bars:
                self._log_entry_quality_filter(
                    symbol,
                    f"SHORT_cross_age_{bearish_cross_age}_bars_above_{self.max_cross_age_bars}",
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
                prev_low = prev.get("low")
                breakdown_momentum_bonus = (
                    prev_low is not None
                    and not (isinstance(prev_low, float) and pd.isna(prev_low))
                    and close_curr < prev_low
                )
                if breakdown_momentum_bonus:
                    strength = min(strength + 0.1, 1.0)
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
                            "bb_position": round(float(bb_position), 4) if bb_position is not None else None,
                            "cross_age_bars": bearish_cross_age,
                            "breakdown_momentum_bonus": breakdown_momentum_bonus,
                            "entry_quality_filter_triggered": False,
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
