"""Breakout strategy built around real structure breaks."""

import pandas as pd
from loguru import logger

from core.analysis.candle_context import analyze_candle_context
from core.analysis.candlestick import PatternDirection
from core.analysis.engine import AnalysisResult
from core.strategy.base import BaseStrategy, MarketRegime, TradeSignal


class BreakoutStrategy(BaseStrategy):
    """Trade structure breakouts only when momentum confirms the move."""

    allowed_regimes = [MarketRegime.TRENDING, MarketRegime.RANGING]

    def __init__(
        self,
        volume_mult: float = 1.5,
        adx_rising_bars: int = 2,
        skip_on_chop: bool = True,
        breakout_body_threshold: float = 0.35,
        short_rsi_floor: float = 34.0,
        short_volume_mult: float = 1.5,
        structure_lookback_bars: int = 20,
    ) -> None:
        self.volume_mult = volume_mult
        self.adx_rising_bars = adx_rising_bars
        self.skip_on_chop = skip_on_chop
        self.breakout_body_threshold = breakout_body_threshold
        self.short_rsi_floor = short_rsi_floor
        self.short_volume_mult = short_volume_mult
        self.structure_lookback_bars = structure_lookback_bars

    @property
    def name(self) -> str:
        return "breakout"

    def _structure_levels(self, df: pd.DataFrame) -> tuple[float, float] | None:
        if len(df) < self.structure_lookback_bars + 1:
            return None
        history = df.iloc[-(self.structure_lookback_bars + 1):-1]
        structure_high = float(history["high"].max())
        structure_low = float(history["low"].min())
        return structure_high, structure_low

    def evaluate_single(
        self,
        symbol: str,
        timeframe: str,
        result: AnalysisResult,
    ) -> list[TradeSignal]:
        signals: list[TradeSignal] = []

        if result.df_enriched is None or len(result.df_enriched) < 30:
            return signals

        if self.skip_on_chop and result.chop and result.chop.is_chop:
            return signals

        df = result.df_enriched
        required = ["open", "high", "low", "close", "volume", "adx", "macd_hist"]
        if not all(column in df.columns for column in required):
            return signals

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(curr["close"])
        open_price = float(curr["open"])
        high = float(curr["high"])
        low = float(curr["low"])
        volume = float(curr["volume"])
        adx = float(curr["adx"]) if not pd.isna(curr["adx"]) else None
        adx_pos = float(curr["adx_pos"]) if "adx_pos" in df.columns and not pd.isna(curr["adx_pos"]) else None
        adx_neg = float(curr["adx_neg"]) if "adx_neg" in df.columns and not pd.isna(curr["adx_neg"]) else None
        rsi = float(curr["rsi"]) if "rsi" in df.columns and not pd.isna(curr["rsi"]) else None

        structure_levels = self._structure_levels(df)
        if structure_levels is None or adx is None:
            return signals
        structure_high, structure_low = structure_levels
        box_height = max(structure_high - structure_low, 1e-9)

        avg_volume = df["volume"].iloc[-20:].mean()
        volume_confirmed = avg_volume > 0 and volume > avg_volume * self.volume_mult
        adx_rising = self._is_adx_rising(df, self.adx_rising_bars)

        macd_hist = float(curr["macd_hist"]) if not pd.isna(curr["macd_hist"]) else 0.0
        macd_hist_prev = float(prev["macd_hist"]) if not pd.isna(prev["macd_hist"]) else 0.0
        macd_expanding_bullish = macd_hist > macd_hist_prev and macd_hist > 0
        macd_expanding_bearish = macd_hist < macd_hist_prev and macd_hist < 0

        candle = self._candle_pattern_bonus(result)
        candle_ctx = analyze_candle_context(df)
        bullish_breakout_confirmed = self._has_breakout_body(
            open_price, close, high, low, direction="LONG"
        )
        bearish_breakout_confirmed = self._has_breakout_body(
            open_price, close, high, low, direction="SHORT"
        )
        # 突破 K 線影線分析
        body = abs(close - open_price)
        upper_wick = high - max(close, open_price)
        lower_wick = min(close, open_price) - low

        if close > structure_high and float(prev["close"]) <= structure_high:
            if volume_confirmed and adx_rising and bullish_breakout_confirmed:
                strength = 0.6
                if macd_expanding_bullish:
                    strength += 0.15
                if candle.get("bullish", 0) > 0:
                    strength += 0.1
                if adx > 30:
                    strength += 0.1
                # 突破 K 線有長下影線（不乾淨突破）→ 扣分
                if body > 0 and lower_wick > body * 0.5:
                    strength -= 0.1
                # K 線群體動量不支持 → 扣分
                if candle_ctx.momentum_score <= 0:
                    strength -= 0.1

                strength = max(min(strength, 1.0), 0.0)
                signals.append(
                    TradeSignal(
                        symbol=symbol,
                        timeframe=timeframe,
                        signal_type="LONG",
                        strength=round(strength, 2),
                        strategy_name=self.name,
                        indicators={
                            "adx": round(adx, 2),
                            "volume_ratio": round(volume / avg_volume, 2),
                            "macd_expanding": macd_expanding_bullish,
                            "breakout_body_ok": bullish_breakout_confirmed,
                            "breakout_price": round(structure_high, 4),
                            "structure_high": round(structure_high, 4),
                            "structure_low": round(structure_low, 4),
                            "breakout_box_height": round(box_height, 4),
                            "close": round(close, 4),
                            "breakout_retest_status": "pending",
                        },
                        reason=(
                            f"Bullish structure breakout above {structure_high:.4f} with "
                            f"{volume / avg_volume:.1f}x volume and rising ADX"
                        ),
                    )
                )
                logger.debug(f"{self.name} LONG breakout: {symbol} {timeframe} ADX={adx:.1f}")

        if close < structure_low and float(prev["close"]) >= structure_low:
            adx_neg_dominant = (
                adx_neg is not None
                and adx_pos is not None
                and adx_neg > adx_pos
            )
            rsi_above_quality_floor = rsi is not None and rsi >= self.short_rsi_floor
            extra_volume_confirmed = avg_volume > 0 and volume > avg_volume * self.short_volume_mult
            if volume_confirmed and adx_rising and bearish_breakout_confirmed:
                strength = 0.6
                if macd_expanding_bearish:
                    strength += 0.15
                if candle.get("bearish", 0) > 0:
                    strength += 0.1
                if adx > 30:
                    strength += 0.1
                # 突破 K 線有長上影線（不乾淨突破）→ 扣分
                if body > 0 and upper_wick > body * 0.5:
                    strength -= 0.1
                # K 線群體動量不支持 → 扣分
                if candle_ctx.momentum_score >= 0:
                    strength -= 0.1

                strength = max(min(strength, 1.0), 0.0)
                signals.append(
                    TradeSignal(
                        symbol=symbol,
                        timeframe=timeframe,
                        signal_type="SHORT",
                        strength=round(strength, 2),
                        strategy_name=self.name,
                        indicators={
                            "adx": round(adx, 2),
                            "volume_ratio": round(volume / avg_volume, 2),
                            "macd_expanding": macd_expanding_bearish,
                            "breakout_body_ok": bearish_breakout_confirmed,
                            "adx_neg": round(adx_neg, 2) if adx_neg is not None else None,
                            "adx_pos": round(adx_pos, 2) if adx_pos is not None else None,
                            "rsi": round(rsi, 2) if rsi is not None else None,
                            "adx_neg_dominant": adx_neg_dominant,
                            "rsi_above_quality_floor": rsi_above_quality_floor,
                            "extra_volume_confirmed": extra_volume_confirmed,
                            "breakout_price": round(structure_low, 4),
                            "structure_high": round(structure_high, 4),
                            "structure_low": round(structure_low, 4),
                            "breakout_box_height": round(box_height, 4),
                            "close": round(close, 4),
                            "breakout_retest_status": "pending",
                        },
                        reason=(
                            f"Bearish structure breakout below {structure_low:.4f} with "
                            f"{volume / avg_volume:.1f}x volume and rising ADX"
                        ),
                    )
                )
                logger.debug(f"{self.name} SHORT breakout: {symbol} {timeframe} ADX={adx:.1f}")

        return signals

    @staticmethod
    def _is_adx_rising(df: pd.DataFrame, bars: int = 3) -> bool:
        if "adx" not in df.columns or len(df) < bars + 1:
            return False
        adx_vals = df["adx"].iloc[-(bars + 1):].values
        for i in range(1, len(adx_vals)):
            if pd.isna(adx_vals[i]) or pd.isna(adx_vals[i - 1]):
                return False
            if adx_vals[i] <= adx_vals[i - 1]:
                return False
        return True

    @staticmethod
    def _candle_pattern_bonus(result: AnalysisResult) -> dict:
        bullish = sum(
            1 for pattern in result.candle_patterns if pattern.direction == PatternDirection.BULLISH
        )
        bearish = sum(
            1 for pattern in result.candle_patterns if pattern.direction == PatternDirection.BEARISH
        )
        return {"bullish": bullish, "bearish": bearish}

    def _has_breakout_body(
        self,
        open_price: float,
        close_price: float,
        high_price: float,
        low_price: float,
        direction: str,
    ) -> bool:
        candle_range = max(high_price - low_price, 1e-9)
        body_ratio = abs(close_price - open_price) / candle_range
        if body_ratio < self.breakout_body_threshold:
            return False
        if direction == "LONG":
            return close_price > open_price
        return close_price < open_price
