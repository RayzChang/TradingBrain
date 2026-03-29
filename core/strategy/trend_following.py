"""Trend following strategy built around pullback continuation candles."""

import pandas as pd
from loguru import logger

from core.analysis.candle_context import analyze_candle_context
from core.analysis.candlestick import PatternDirection
from core.analysis.engine import AnalysisResult
from core.strategy.base import BaseStrategy, MarketRegime, TradeSignal


class TrendFollowingStrategy(BaseStrategy):
    """Trade pullback continuations instead of chasing raw EMA crosses."""

    allowed_regimes = [MarketRegime.TRENDING, MarketRegime.RANGING]

    def __init__(
        self,
        adx_min: float = 20.0,
        skip_on_chop: bool = True,
        long_rsi_floor: float = 45.0,
        long_rsi_ceiling: float = 72.0,
        short_rsi_floor: float = 28.0,
        short_rsi_ceiling: float = 55.0,
        long_bb_position_ceiling: float = 0.85,
        long_rsi_quality_ceiling: float = 63.0,
        long_rsi_bb_position_ceiling: float = 0.75,
        short_bb_position_floor: float = 0.15,
        short_rsi_quality_floor: float = 37.0,
        short_rsi_bb_position_floor: float = 0.25,
        max_cross_age_bars: int = 30,
        pullback_lookback_bars: int = 6,
        ema_pullback_tolerance: float = 0.004,
        ema50_fail_tolerance: float = 0.008,
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
        self.pullback_lookback_bars = pullback_lookback_bars
        self.ema_pullback_tolerance = ema_pullback_tolerance
        self.ema50_fail_tolerance = ema50_fail_tolerance

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

    @staticmethod
    def _candle_metrics(row: pd.Series) -> tuple[float, float, float, float, float]:
        open_price = float(row.get("open"))
        close_price = float(row.get("close"))
        high_price = float(row.get("high"))
        low_price = float(row.get("low"))
        candle_range = max(high_price - low_price, 1e-9)
        body = abs(close_price - open_price)
        lower_wick = min(open_price, close_price) - low_price
        upper_wick = high_price - max(open_price, close_price)
        return open_price, close_price, candle_range, body, max(lower_wick, 0.0), max(upper_wick, 0.0)

    def _recent_pullback_window(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) <= 1:
            return df.iloc[0:0]
        start = max(0, len(df) - 1 - self.pullback_lookback_bars)
        return df.iloc[start:-1]

    def evaluate_single(
        self,
        symbol: str,
        timeframe: str,
        result: AnalysisResult,
    ) -> list[TradeSignal]:
        signals: list[TradeSignal] = []

        if result.df_enriched is None or len(result.df_enriched) < 4:
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
        open_curr = curr.get("open")
        high_curr = curr.get("high")
        low_curr = curr.get("low")
        prev_high = prev.get("high")
        prev_low = prev.get("low")
        prev_close = prev.get("close")
        rsi_curr = curr.get("rsi")
        macd_hist_curr = curr.get("macd_hist")
        macd_hist_prev = prev.get("macd_hist")
        bb_position = self._get_bb_position(curr)

        if any(
            value is None or (isinstance(value, float) and pd.isna(value))
            for value in (
                ema9_prev,
                ema21_prev,
                ema9_curr,
                ema21_curr,
                open_curr,
                high_curr,
                low_curr,
                prev_high,
                prev_low,
                prev_close,
            )
        ):
            return signals

        candle_bonus = self._candle_pattern_bonus(result)
        candle_confirm_bullish = self._has_confident_pattern(result, "bullish")
        candle_confirm_bearish = self._has_confident_pattern(result, "bearish")
        candle_ctx = analyze_candle_context(df)
        fib_info = self._fibonacci_bonus(result, float(curr.get("close", 0)))
        divergence_bonus = self._divergence_bonus(result)
        bullish_cross_age = self._get_cross_age_bars(df, bullish=True)
        bearish_cross_age = self._get_cross_age_bars(df, bullish=False)
        pullback_window = self._recent_pullback_window(df)
        if pullback_window.empty:
            return signals
        recent_pullback_low = float(pullback_window["low"].min())
        recent_pullback_high = float(pullback_window["high"].max())
        open_curr_f, close_curr_f, candle_range, body, lower_wick, upper_wick = self._candle_metrics(curr)

        if ema9_curr > ema21_curr:
            bullish_stack_ok = True
            bullish_di_ok = True
            bullish_momentum_ok = True
            bullish_pullback_ok = True
            bullish_rejection_ok = True
            bullish_trigger_ok = True

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
                    )
                    bullish_pullback_ok = bool(
                        recent_pullback_low <= ema21_curr * (1 + self.ema_pullback_tolerance)
                        and recent_pullback_low >= ema50_curr * (1 - self.ema50_fail_tolerance)
                    )
                    bullish_rejection_ok = bool(
                        close_curr_f > open_curr_f
                        and close_curr_f >= (low_curr + candle_range * 0.6)
                    )
                    bullish_trigger_ok = bool(
                        close_curr_f > ema9_curr
                        and close_curr_f > prev_close
                        and (
                            close_curr_f > prev_high
                            or lower_wick >= body
                        )
                    )

            if (
                not bullish_stack_ok
                or not bullish_di_ok
                or not bullish_momentum_ok
                or not bullish_pullback_ok
                or not bullish_rejection_ok
                or not bullish_trigger_ok
            ):
                logger.debug(
                    f"{self.name} LONG filtered: {symbol} {timeframe} "
                    f"stack={bullish_stack_ok} di={bullish_di_ok} "
                    f"momentum={bullish_momentum_ok} pullback={bullish_pullback_ok} "
                    f"rejection={bullish_rejection_ok} trigger={bullish_trigger_ok}"
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
            strength = min(0.5 + (adx - self.adx_min) / 50.0, 1.0)
            strength = max(0.0, strength)

            # K 線確認（軟因子）：有確認加分，沒確認扣分
            _has_candle_confirm = bool(
                candle_confirm_bullish
                or candle_ctx.momentum_score > 0.1
                or candle_ctx.rejection_count >= 2
            )
            if _has_candle_confirm:
                strength = min(strength + 0.1, 1.0)
            else:
                strength = strength * 0.75

            if candle_bonus.get("bullish", 0) > 0:
                strength = min(strength + 0.15, 1.0)
            if fib_info.get("near_support", False):
                strength = min(strength + 0.1, 1.0)
            if divergence_bonus.get("bullish", False):
                strength = min(strength + 0.1, 1.0)
            if candle_bonus.get("bearish", 0) > 0:
                strength = max(strength - 0.15, 0.0)

            # 量能軟檢查：低量降信心
            if "volume" in df.columns:
                curr_vol = pd.to_numeric(curr.get("volume", 0), errors="coerce")
                avg_vol = pd.to_numeric(df["volume"].iloc[-20:], errors="coerce").mean()
                if avg_vol > 0 and curr_vol < avg_vol * 0.8:
                    strength = strength * 0.7

            if strength >= 0.3:
                continuation_break = bool(close_curr > prev_high)
                if continuation_break:
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
                            "recent_pullback_low": round(recent_pullback_low, 4),
                            "pullback_to_ema21": bullish_pullback_ok,
                            "pullback_held_above_ema50": bool(
                                recent_pullback_low >= float(ema50_curr) * (1 - self.ema50_fail_tolerance)
                            ),
                            "rejection_candle": bullish_rejection_ok,
                            "continuation_break_confirmed": continuation_break,
                            "entry_quality_filter_triggered": False,
                            "bullish_stack_ok": bullish_stack_ok,
                            "bullish_momentum_ok": bullish_momentum_ok,
                            "candle_confirm": candle_bonus,
                            "fib_support": fib_info.get("near_support", False),
                            "divergence_bullish": divergence_bonus.get("bullish", False),
                        },
                        reason=(
                            "Bullish pullback continuation after support rejection"
                            + self._build_reason_suffix(candle_bonus, fib_info, divergence_bonus, "LONG")
                        ),
                    )
                )
                logger.debug(f"{self.name} LONG signal: {symbol} {timeframe} ADX={adx:.1f} strength={strength:.2f}")

        if ema9_curr < ema21_curr:
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
            )
            bearish_pullback_ok = bool(
                recent_pullback_high >= ema21_curr * (1 - self.ema_pullback_tolerance)
                and recent_pullback_high <= ema50_curr * (1 + self.ema50_fail_tolerance)
            )
            bearish_rejection_ok = bool(
                close_curr_f < open_curr_f
                and close_curr_f <= (high_curr - candle_range * 0.6)
            )
            bearish_trigger_ok = bool(
                close_curr_f < ema9_curr
                and close_curr_f < prev_close
                and (
                    close_curr_f < prev_low
                    or upper_wick >= body
                )
            )

            if (
                not bearish_stack_ok
                or not bearish_di_ok
                or not bearish_momentum_ok
                or not bearish_pullback_ok
                or not bearish_rejection_ok
                or not bearish_trigger_ok
            ):
                logger.debug(
                    f"{self.name} SHORT filtered: {symbol} {timeframe} "
                    f"stack={bearish_stack_ok} di={bearish_di_ok} "
                    f"momentum={bearish_momentum_ok} pullback={bearish_pullback_ok} "
                    f"rejection={bearish_rejection_ok} trigger={bearish_trigger_ok}"
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
            strength = min(0.5 + (adx - self.adx_min) / 50.0, 1.0)
            strength = max(0.0, strength)

            # K 線確認（軟因子）
            _has_candle_confirm_s = bool(
                candle_confirm_bearish
                or candle_ctx.momentum_score < -0.1
                or candle_ctx.rejection_count >= 2
            )
            if _has_candle_confirm_s:
                strength = min(strength + 0.1, 1.0)
            else:
                strength = strength * 0.75

            if candle_bonus.get("bearish", 0) > 0:
                strength = min(strength + 0.15, 1.0)
            if fib_info.get("near_resistance", False):
                strength = min(strength + 0.1, 1.0)
            if divergence_bonus.get("bearish", False):
                strength = min(strength + 0.1, 1.0)
            if candle_bonus.get("bullish", 0) > 0:
                strength = max(strength - 0.15, 0.0)

            # 量能軟檢查：低量降信心
            if "volume" in df.columns:
                curr_vol_s = pd.to_numeric(curr.get("volume", 0), errors="coerce")
                avg_vol_s = pd.to_numeric(df["volume"].iloc[-20:], errors="coerce").mean()
                if avg_vol_s > 0 and curr_vol_s < avg_vol_s * 0.8:
                    strength = strength * 0.7

            if strength >= 0.3:
                continuation_break = bool(close_curr < prev_low)
                if continuation_break:
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
                            "recent_pullback_high": round(recent_pullback_high, 4),
                            "pullback_to_ema21": bearish_pullback_ok,
                            "pullback_held_below_ema50": bool(
                                recent_pullback_high <= float(ema50_curr) * (1 + self.ema50_fail_tolerance)
                            ),
                            "rejection_candle": bearish_rejection_ok,
                            "continuation_break_confirmed": continuation_break,
                            "entry_quality_filter_triggered": False,
                            "bearish_stack_ok": bearish_stack_ok,
                            "bearish_momentum_ok": bearish_momentum_ok,
                            "candle_confirm": candle_bonus,
                            "fib_resistance": fib_info.get("near_resistance", False),
                            "divergence_bearish": divergence_bonus.get("bearish", False),
                        },
                        reason=(
                            "Bearish pullback continuation after resistance rejection"
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
    def _has_confident_pattern(result: AnalysisResult, direction: str, min_confidence: float = 0.5) -> bool:
        """Check if any candle pattern matches the direction with sufficient confidence."""
        target = PatternDirection.BULLISH if direction == "bullish" else PatternDirection.BEARISH
        return any(
            p.direction == target and p.confidence >= min_confidence
            for p in result.candle_patterns
        )

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
