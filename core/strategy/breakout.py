"""Breakout strategy with volume and momentum confirmation."""

import pandas as pd
from loguru import logger

from core.analysis.candlestick import PatternDirection
from core.analysis.engine import AnalysisResult
from core.strategy.base import BaseStrategy, MarketRegime, TradeSignal


class BreakoutStrategy(BaseStrategy):
    """Trade breakouts only when momentum confirms the move."""

    allowed_regimes = [MarketRegime.TRENDING]

    def __init__(
        self,
        volume_mult: float = 1.5,
        adx_rising_bars: int = 3,
        skip_on_chop: bool = True,
        breakout_body_threshold: float = 0.35,
        short_rsi_floor: float = 34.0,
        short_volume_mult: float = 1.5,
    ) -> None:
        self.volume_mult = volume_mult
        self.adx_rising_bars = adx_rising_bars
        self.skip_on_chop = skip_on_chop
        self.breakout_body_threshold = breakout_body_threshold
        self.short_rsi_floor = short_rsi_floor
        self.short_volume_mult = short_volume_mult

    @property
    def name(self) -> str:
        return "breakout"

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
        required = [
            "open",
            "high",
            "low",
            "close",
            "bb_upper",
            "bb_lower",
            "volume",
            "adx",
            "macd_hist",
        ]
        if not all(column in df.columns for column in required):
            return signals

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(curr["close"])
        open_price = float(curr["open"])
        high = float(curr["high"])
        low = float(curr["low"])
        bb_upper = float(curr["bb_upper"]) if not pd.isna(curr["bb_upper"]) else None
        bb_lower = float(curr["bb_lower"]) if not pd.isna(curr["bb_lower"]) else None
        volume = float(curr["volume"])
        adx = float(curr["adx"]) if not pd.isna(curr["adx"]) else None
        adx_pos = float(curr["adx_pos"]) if "adx_pos" in df.columns and not pd.isna(curr["adx_pos"]) else None
        adx_neg = float(curr["adx_neg"]) if "adx_neg" in df.columns and not pd.isna(curr["adx_neg"]) else None
        rsi = float(curr["rsi"]) if "rsi" in df.columns and not pd.isna(curr["rsi"]) else None

        if bb_upper is None or bb_lower is None or adx is None:
            return signals

        avg_volume = df["volume"].iloc[-20:].mean()
        volume_confirmed = avg_volume > 0 and volume > avg_volume * self.volume_mult
        adx_rising = self._is_adx_rising(df, self.adx_rising_bars)

        macd_hist = float(curr["macd_hist"]) if not pd.isna(curr["macd_hist"]) else 0.0
        macd_hist_prev = float(prev["macd_hist"]) if not pd.isna(prev["macd_hist"]) else 0.0
        macd_expanding_bullish = macd_hist > macd_hist_prev and macd_hist > 0
        macd_expanding_bearish = macd_hist < macd_hist_prev and macd_hist < 0

        candle = self._candle_pattern_bonus(result)
        bullish_breakout_confirmed = self._has_breakout_body(
            open_price, close, high, low, direction="LONG"
        )
        bearish_breakout_confirmed = self._has_breakout_body(
            open_price, close, high, low, direction="SHORT"
        )

        if close > bb_upper and float(prev["close"]) <= float(prev.get("bb_upper", bb_upper)):
            if volume_confirmed and adx_rising and bullish_breakout_confirmed:
                strength = 0.6
                if macd_expanding_bullish:
                    strength += 0.15
                if candle.get("bullish", 0) > 0:
                    strength += 0.1
                if adx > 30:
                    strength += 0.1

                strength = min(strength, 1.0)
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
                            "bb_upper": round(bb_upper, 4),
                            "close": round(close, 4),
                            "breakout_retest_status": "pending",
                        },
                        reason=(
                            f"Bullish breakout above upper band with "
                            f"{volume / avg_volume:.1f}x volume and rising ADX"
                        ),
                    )
                )
                logger.debug(f"{self.name} LONG breakout: {symbol} {timeframe} ADX={adx:.1f}")

        if close < bb_lower and float(prev["close"]) >= float(prev.get("bb_lower", bb_lower)):
            short_structure_ok = (
                bearish_breakout_confirmed
                and adx_neg is not None
                and adx_pos is not None
                and adx_neg > adx_pos
                and rsi is not None
                and rsi >= self.short_rsi_floor
                and volume > avg_volume * self.short_volume_mult
                and macd_expanding_bearish
            )
            if volume_confirmed and adx_rising and short_structure_ok:
                strength = 0.6
                if macd_expanding_bearish:
                    strength += 0.15
                if candle.get("bearish", 0) > 0:
                    strength += 0.1
                if adx > 30:
                    strength += 0.1

                strength = min(strength, 1.0)
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
                            "adx_neg": round(adx_neg, 2),
                            "adx_pos": round(adx_pos, 2),
                            "rsi": round(rsi, 2),
                            "bb_lower": round(bb_lower, 4),
                            "close": round(close, 4),
                            "breakout_retest_status": "pending",
                        },
                        reason=(
                            f"Bearish breakout below lower band with "
                            f"{volume / avg_volume:.1f}x volume and bearish confirmation"
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
