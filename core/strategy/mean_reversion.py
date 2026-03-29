"""Mean reversion strategy focused on real range-edge reversals."""

import pandas as pd
from loguru import logger

from core.analysis.candle_context import analyze_candle_context
from core.analysis.candlestick import PatternDirection
from core.analysis.engine import AnalysisResult, FullAnalysis
from core.strategy.base import BaseStrategy, MarketRegime, TradeSignal


class MeanReversionStrategy(BaseStrategy):
    """Fade only real range edges instead of blindly fading Bollinger touches."""

    allowed_regimes = [MarketRegime.RANGING]

    def __init__(
        self,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        bb_touch_threshold: float = 0.02,
        skip_on_chop: bool = True,
        short_rsi_floor: float = 65.0,
        long_rsi_ceiling: float = 35.0,
        range_lookback_bars: int = 24,
        range_edge_pct: float = 0.18,
    ) -> None:
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.bb_touch_threshold = bb_touch_threshold
        self.skip_on_chop = skip_on_chop
        self.short_rsi_floor = short_rsi_floor
        self.long_rsi_ceiling = long_rsi_ceiling
        self.range_lookback_bars = range_lookback_bars
        self.range_edge_pct = range_edge_pct

    @property
    def name(self) -> str:
        return "mean_reversion"

    @staticmethod
    def _safe_price(row: pd.Series, key: str, fallback: float | None = None) -> float | None:
        value = row.get(key, fallback)
        if value is None or pd.isna(value):
            return fallback
        return float(value)

    def _range_context(self, df: pd.DataFrame) -> tuple[float, float, float] | None:
        if df.empty:
            return None
        lookback = df.tail(self.range_lookback_bars).copy()
        highs = lookback["high"] if "high" in lookback.columns else lookback[["open", "close"]].max(axis=1)
        lows = lookback["low"] if "low" in lookback.columns else lookback[["open", "close"]].min(axis=1)
        range_high = float(highs.max())
        range_low = float(lows.min())
        range_width = range_high - range_low
        if range_width <= 0:
            return None
        edge_band = max(range_width * self.range_edge_pct, range_high * 0.003)
        return range_low, range_high, edge_band

    @staticmethod
    def _reversal_candle(
        *,
        direction: str,
        open_price: float,
        close_price: float,
        high_price: float,
        low_price: float,
        prev_close: float,
        prev_extreme: float,
    ) -> bool:
        candle_range = max(high_price - low_price, 1e-9)
        body = abs(close_price - open_price)
        lower_wick = min(open_price, close_price) - low_price
        upper_wick = high_price - max(open_price, close_price)
        if direction == "LONG":
            return bool(
                close_price > open_price
                and close_price >= prev_close
                and close_price >= low_price + candle_range * 0.6
                and (lower_wick >= body * 0.6 or close_price > prev_extreme)
            )
        return bool(
            close_price < open_price
            and close_price <= prev_close
            and close_price <= high_price - candle_range * 0.6
            and (upper_wick >= body * 0.6 or close_price < prev_extreme)
        )

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
        high_price = self._safe_price(curr, "high", fallback=max(float(open_price), float(close)) if close is not None and open_price is not None else None)
        low_price = self._safe_price(curr, "low", fallback=min(float(open_price), float(close)) if close is not None and open_price is not None else None)
        prev_high = self._safe_price(prev, "high", fallback=max(float(prev.get("open", prev_close)), float(prev_close)) if prev_close is not None else None)
        prev_low = self._safe_price(prev, "low", fallback=min(float(prev.get("open", prev_close)), float(prev_close)) if prev_close is not None else None)

        if (
            close is None
            or close <= 0
            or open_price is None
            or prev_close is None
            or high_price is None
            or low_price is None
            or prev_high is None
            or prev_low is None
        ):
            return signals

        range_context = self._range_context(result.df_enriched)
        if range_context is None:
            return signals
        range_low, range_high, edge_band = range_context
        range_mid = (range_low + range_high) / 2

        candle_ctx = analyze_candle_context(result.df_enriched)
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

        near_range_low = bool(low_price <= range_low + edge_band and close <= range_mid)
        near_range_high = bool(high_price >= range_high - edge_band and close >= range_mid)

        if bb_lower is not None and not pd.isna(bb_lower):
            dist_lower = (close - float(bb_lower)) / close
            bullish_reversal = self._reversal_candle(
                direction="LONG",
                open_price=float(open_price),
                close_price=float(close),
                high_price=high_price,
                low_price=low_price,
                prev_close=float(prev_close),
                prev_extreme=float(prev_high),
            )
            if near_range_low and dist_lower <= self.bb_touch_threshold and rsi_f <= self.long_rsi_ceiling:
                # 動量門檻：K 線群體動量太空不做多（反轉失敗率高）
                if candle_ctx.momentum_score < -0.2:
                    logger.debug(
                        f"{self.name} LONG blocked: {symbol} momentum={candle_ctx.momentum_score:.2f} too bearish for MR long"
                    )
                else:
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

                    # K 線確認：必須有 reversal candle 或高信心看多型態
                    has_confident_bull = any(
                        p.direction == PatternDirection.BULLISH and p.confidence >= 0.5
                        for p in result.candle_patterns
                    )
                    has_bull_confirm = has_bull_div or has_confident_bull
                    if bullish_reversal or has_bull_confirm:
                        if not (bullish_reversal and has_bull_confirm):
                            strength = round(strength * 0.75, 4)

                        # 量能軟檢查
                        if "volume" in result.df_enriched.columns:
                            curr_vol = pd.to_numeric(curr.get("volume", 0), errors="coerce")
                            avg_vol = pd.to_numeric(result.df_enriched["volume"].iloc[-20:], errors="coerce").mean()
                            if avg_vol > 0 and curr_vol < avg_vol * 0.8:
                                strength = strength * 0.7

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
                                    "range_low": round(range_low, 4),
                                    "range_high": round(range_high, 4),
                                    "edge_band": round(edge_band, 4),
                                    "near_range_low": near_range_low,
                                    "divergence_bullish": has_bull_div,
                                    "candle_bullish": candle_bonus.get("bullish", 0),
                                    "fib_support": fib_info.get("near_support", False),
                                    "bullish_reversal": bullish_reversal,
                                    "candle_momentum": round(candle_ctx.momentum_score, 4),
                                },
                                reason="Range-edge bullish reversal near support",
                            )
                        )
                        logger.debug(
                            f"{self.name} LONG signal: {symbol} {timeframe} "
                            f"RSI={rsi_f:.1f} strength={strength:.2f}"
                        )

        if bb_upper is not None and not pd.isna(bb_upper):
            dist_upper = (float(bb_upper) - close) / close
            bearish_reversal = self._reversal_candle(
                direction="SHORT",
                open_price=float(open_price),
                close_price=float(close),
                high_price=high_price,
                low_price=low_price,
                prev_close=float(prev_close),
                prev_extreme=float(prev_low),
            )
            if near_range_high and dist_upper <= self.bb_touch_threshold and rsi_f >= self.short_rsi_floor:
                # 動量門檻：K 線群體動量太多不做空（反轉失敗率高）
                if candle_ctx.momentum_score > 0.2:
                    logger.debug(
                        f"{self.name} SHORT blocked: {symbol} momentum={candle_ctx.momentum_score:.2f} too bullish for MR short"
                    )
                else:
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

                    # K 線確認：必須有 reversal candle 或高信心看空型態
                    has_confident_bear = any(
                        p.direction == PatternDirection.BEARISH and p.confidence >= 0.5
                        for p in result.candle_patterns
                    )
                    has_bear_confirm = has_bear_div or has_confident_bear
                    if bearish_reversal or has_bear_confirm:
                        if not (bearish_reversal and has_bear_confirm):
                            strength = round(strength * 0.75, 4)

                        # 量能軟檢查
                        if "volume" in result.df_enriched.columns:
                            curr_vol = pd.to_numeric(curr.get("volume", 0), errors="coerce")
                            avg_vol = pd.to_numeric(result.df_enriched["volume"].iloc[-20:], errors="coerce").mean()
                            if avg_vol > 0 and curr_vol < avg_vol * 0.8:
                                strength = strength * 0.7

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
                                    "range_low": round(range_low, 4),
                                    "range_high": round(range_high, 4),
                                    "edge_band": round(edge_band, 4),
                                    "near_range_high": near_range_high,
                                    "divergence_bearish": has_bear_div,
                                    "candle_bearish": candle_bonus.get("bearish", 0),
                                    "fib_resistance": fib_info.get("near_resistance", False),
                                    "bearish_reversal": bearish_reversal,
                                    "candle_momentum": round(candle_ctx.momentum_score, 4),
                                },
                                reason="Range-edge bearish reversal near resistance",
                            )
                        )
                        logger.debug(
                            f"{self.name} SHORT signal: {symbol} {timeframe} "
                            f"RSI={rsi_f:.1f} strength={strength:.2f}"
                        )

        return signals

    def evaluate_full(
        self,
        full: FullAnalysis,
        primary_tf: str | None = None,
    ) -> list[TradeSignal]:
        """Override: MR SHORT 額外要求 1h LEAN_BEARISH 或 4h RSI > 65."""
        signals = super().evaluate_full(full, primary_tf)
        if not signals:
            return signals

        filtered: list[TradeSignal] = []
        for sig in signals:
            if sig.signal_type != "SHORT":
                filtered.append(sig)
                continue

            # 檢查 1h 方向
            htf_1h_dir = None
            if full.mtf and full.mtf.details:
                htf_1h_dir = full.mtf.details.get("1h")

            # 檢查 4h RSI
            htf_4h_rsi = None
            result_4h = full.single_tf_results.get("4h")
            if result_4h and result_4h.indicators:
                raw_rsi = result_4h.indicators.get("rsi")
                if raw_rsi is not None:
                    try:
                        htf_4h_rsi = float(raw_rsi)
                    except (TypeError, ValueError):
                        pass

            has_1h_bearish = htf_1h_dir in ("BEARISH", "LEAN_BEARISH")
            has_4h_rsi_high = htf_4h_rsi is not None and htf_4h_rsi > 65

            if has_1h_bearish or has_4h_rsi_high:
                sig.indicators["mr_short_htf_confirmed"] = True
                sig.indicators["htf_1h_direction"] = htf_1h_dir
                sig.indicators["htf_4h_rsi"] = htf_4h_rsi
                filtered.append(sig)
            else:
                logger.info(
                    f"MR SHORT 過濾: {sig.symbol} 1h={htf_1h_dir} 4h_rsi={htf_4h_rsi} "
                    f"(需要 1h LEAN_BEARISH 或 4h RSI>65)"
                )

        return filtered

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
