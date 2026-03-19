"""Strategy base classes and market-regime routing."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from loguru import logger

from core.analysis.engine import AnalysisResult, FullAnalysis


def _safe_float(value: Any) -> float | None:
    """Return a float when possible, otherwise None."""
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(value_f):
        return None
    return value_f


@dataclass
class RegimeAssessment:
    """Structured output for the market-regime classifier."""

    regime: str
    trend_score: float
    range_score: float
    volatility_score: float
    metrics: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def to_indicator_payload(self) -> dict[str, Any]:
        """Flatten the assessment for signal metadata and logging."""
        return {
            "market_regime": self.regime,
            "regime_scores": {
                "trend": round(self.trend_score, 2),
                "range": round(self.range_score, 2),
                "volatile": round(self.volatility_score, 2),
            },
            "regime_metrics": self.metrics,
            "regime_reasons": self.reasons,
        }


@dataclass
class RegimeState:
    """Runtime hysteresis state for one symbol/timeframe pair."""

    active_regime: str
    bar_token: str
    bar_index: int = 0
    last_switch_index: int = 0


class MarketRegime:
    """Market-regime classifier used by all strategies."""

    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"

    MIN_BARS_BETWEEN_SWITCHES = 3
    TREND_EXIT_ADX_BUFFER = 18.0
    VOLATILITY_SCORE_TRIGGER = 1.6
    VOLATILITY_TREND_CAP = 2.6
    _state_by_key: dict[tuple[str, str], RegimeState] = {}

    @staticmethod
    def _bar_token(result: AnalysisResult) -> str:
        """Return a stable identifier for the latest bar."""
        if result.df_enriched is None or result.df_enriched.empty:
            return "unknown"

        latest = result.df_enriched.iloc[-1]
        for key in ("open_time", "close_time", "timestamp", "datetime", "time"):
            value = latest.get(key)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            if isinstance(value, pd.Timestamp):
                return value.isoformat()
            return str(value)

        if not isinstance(result.df_enriched.index, pd.RangeIndex):
            idx_value = result.df_enriched.index[-1]
            if isinstance(idx_value, pd.Timestamp):
                return idx_value.isoformat()
            return str(idx_value)

        close = latest.get("close")
        return f"row-{len(result.df_enriched)}-{close}"

    @classmethod
    def reset_hysteresis(cls) -> None:
        """Clear runtime regime state. Used by tests and manual reset flows."""
        cls._state_by_key.clear()

    @classmethod
    def _apply_hysteresis(
        cls,
        result: AnalysisResult,
        assessment: RegimeAssessment,
        *,
        adx: float | None,
    ) -> RegimeAssessment:
        """Hold regime long enough to reduce 15m flip-flopping."""
        if assessment.regime in {cls.UNKNOWN, cls.VOLATILE}:
            # Unknown should not anchor state; volatile remains event-driven.
            if assessment.regime == cls.VOLATILE:
                key = (result.symbol, result.timeframe)
                token = cls._bar_token(result)
                state = cls._state_by_key.get(key)
                if state is None:
                    cls._state_by_key[key] = RegimeState(
                        active_regime=assessment.regime,
                        bar_token=token,
                    )
                else:
                    if token != state.bar_token:
                        state.bar_index += 1
                        state.bar_token = token
                    if state.active_regime != assessment.regime:
                        state.active_regime = assessment.regime
                        state.last_switch_index = state.bar_index
            return assessment

        key = (result.symbol, result.timeframe)
        token = cls._bar_token(result)
        state = cls._state_by_key.get(key)
        if state is None:
            cls._state_by_key[key] = RegimeState(
                active_regime=assessment.regime,
                bar_token=token,
            )
            return assessment

        if token != state.bar_token:
            state.bar_index += 1
            state.bar_token = token

        if assessment.regime == state.active_regime:
            return assessment

        bars_since_switch = state.bar_index - state.last_switch_index
        if (
            state.active_regime == cls.TRENDING
            and assessment.regime == cls.RANGING
            and adx is not None
            and adx >= cls.TREND_EXIT_ADX_BUFFER
        ):
            reasons = [
                *assessment.reasons,
                (
                    "hysteresis hold: trending->ranging requires "
                    f"adx < {cls.TREND_EXIT_ADX_BUFFER:.0f}"
                ),
            ]
            return RegimeAssessment(
                regime=state.active_regime,
                trend_score=assessment.trend_score,
                range_score=assessment.range_score,
                volatility_score=assessment.volatility_score,
                metrics={
                    **assessment.metrics,
                    "hysteresis_active_regime": state.active_regime,
                    "hysteresis_bars_since_switch": bars_since_switch,
                },
                reasons=reasons,
            )

        if bars_since_switch < cls.MIN_BARS_BETWEEN_SWITCHES:
            reasons = [
                *assessment.reasons,
                (
                    "hysteresis hold: "
                    f"{bars_since_switch}/{cls.MIN_BARS_BETWEEN_SWITCHES} bars since last switch"
                ),
            ]
            return RegimeAssessment(
                regime=state.active_regime,
                trend_score=assessment.trend_score,
                range_score=assessment.range_score,
                volatility_score=assessment.volatility_score,
                metrics={
                    **assessment.metrics,
                    "hysteresis_active_regime": state.active_regime,
                    "hysteresis_bars_since_switch": bars_since_switch,
                },
                reasons=reasons,
            )

        state.active_regime = assessment.regime
        state.last_switch_index = state.bar_index
        return RegimeAssessment(
            regime=assessment.regime,
            trend_score=assessment.trend_score,
            range_score=assessment.range_score,
            volatility_score=assessment.volatility_score,
            metrics={
                **assessment.metrics,
                "hysteresis_active_regime": assessment.regime,
                "hysteresis_bars_since_switch": bars_since_switch,
            },
            reasons=[*assessment.reasons, "hysteresis switch accepted"],
        )

    @staticmethod
    def _htf_trend_support(
        result: AnalysisResult,
        full: FullAnalysis | None,
    ) -> tuple[int, int, dict[str, str]]:
        """Measure 1h/4h trend agreement for the current timeframe."""
        current_trend = result.indicators.get("trend")
        if current_trend not in {"BULLISH", "BEARISH"} or full is None:
            return 0, 0, {}

        aligned = 0
        conflicting = 0
        details: dict[str, str] = {}
        for tf in ("1h", "4h"):
            tf_result = full.single_tf_results.get(tf)
            if tf_result is None:
                continue
            tf_trend = tf_result.indicators.get("trend")
            if tf_trend not in {"BULLISH", "BEARISH", "NEUTRAL"}:
                continue
            details[tf] = tf_trend
            if tf_trend == current_trend:
                aligned += 1
            elif tf_trend in {"BULLISH", "BEARISH"} and tf_trend != current_trend:
                conflicting += 1
        return aligned, conflicting, details

    @staticmethod
    def assess(
        result: AnalysisResult,
        full: FullAnalysis | None = None,
    ) -> RegimeAssessment:
        """Classify the current market regime using multiple factors."""
        if result.df_enriched is None or result.df_enriched.empty:
            return RegimeAssessment(
                regime=MarketRegime.UNKNOWN,
                trend_score=0.0,
                range_score=0.0,
                volatility_score=0.0,
                reasons=["missing enriched dataframe"],
            )

        latest = result.df_enriched.iloc[-1]
        adx = _safe_float(latest.get("adx", result.indicators.get("adx")))
        adx_pos = _safe_float(latest.get("adx_pos", result.indicators.get("adx_pos")))
        adx_neg = _safe_float(latest.get("adx_neg", result.indicators.get("adx_neg")))
        bb_width = _safe_float(latest.get("bb_width", result.indicators.get("bb_width")))
        atr = _safe_float(latest.get("atr", result.indicators.get("atr")))
        close = _safe_float(latest.get("close", result.indicators.get("close")))
        atr_ratio = None if atr is None or close in (None, 0) else atr / close
        trend_direction = result.indicators.get("trend")
        di_spread = None
        if adx_pos is not None and adx_neg is not None:
            di_spread = abs(adx_pos - adx_neg)

        htf_aligned, htf_conflicting, htf_details = MarketRegime._htf_trend_support(
            result, full
        )

        metrics = {
            "adx": round(adx, 2) if adx is not None else None,
            "adx_pos": round(adx_pos, 2) if adx_pos is not None else None,
            "adx_neg": round(adx_neg, 2) if adx_neg is not None else None,
            "di_spread": round(di_spread, 2) if di_spread is not None else None,
            "bb_width": round(bb_width, 4) if bb_width is not None else None,
            "atr_ratio": round(atr_ratio, 6) if atr_ratio is not None else None,
            "trend_direction": trend_direction,
            "htf_aligned": htf_aligned,
            "htf_conflicting": htf_conflicting,
            "htf_details": htf_details,
            "chop_score": result.chop.score if result.chop else None,
        }

        if adx is None or di_spread is None or bb_width is None or atr_ratio is None:
            return RegimeAssessment(
                regime=MarketRegime.UNKNOWN,
                trend_score=0.0,
                range_score=0.0,
                volatility_score=0.0,
                metrics=metrics,
                reasons=["missing indicator inputs for regime classification"],
            )

        trend_score = 0.0
        range_score = 0.0
        volatility_score = 0.0
        trend_reasons: list[str] = []
        range_reasons: list[str] = []
        volatility_reasons: list[str] = []

        if adx >= 25:
            trend_score += 1.5
            trend_reasons.append(f"adx {adx:.1f} >= 25")
        elif adx >= 20:
            trend_score += 1.0
            trend_reasons.append(f"adx {adx:.1f} >= 20")
        elif adx <= 17:
            range_score += 1.1
            range_reasons.append(f"adx {adx:.1f} <= 17")

        if di_spread >= 12:
            trend_score += 1.0
            trend_reasons.append(f"di spread {di_spread:.1f} >= 12")
        elif di_spread >= 7:
            trend_score += 0.6
            trend_reasons.append(f"di spread {di_spread:.1f} >= 7")
        elif di_spread <= 4:
            range_score += 0.8
            range_reasons.append(f"di spread {di_spread:.1f} <= 4")

        if bb_width >= 12:
            volatility_score += 1.2
            volatility_reasons.append(f"bb width {bb_width:.2f} >= 12")
        elif bb_width >= 6:
            trend_score += 0.4
            trend_reasons.append(f"bb width {bb_width:.2f} supports expansion")
        elif bb_width <= 4.5:
            range_score += 0.9
            range_reasons.append(f"bb width {bb_width:.2f} <= 4.5")

        if atr_ratio >= 0.03:
            volatility_score += 1.4
            volatility_reasons.append(f"atr ratio {atr_ratio:.4f} >= 0.03")
        elif atr_ratio >= 0.018:
            volatility_score += 0.7
            volatility_reasons.append(f"atr ratio {atr_ratio:.4f} >= 0.018")
        elif 0.004 <= atr_ratio <= 0.018:
            trend_score += 0.4
            trend_reasons.append(f"atr ratio {atr_ratio:.4f} in trend window")
        elif atr_ratio < 0.004:
            range_score += 0.5
            range_reasons.append(f"atr ratio {atr_ratio:.4f} < 0.004")

        if trend_direction in {"BULLISH", "BEARISH"}:
            trend_score += 0.4
            trend_reasons.append(f"trend direction {trend_direction}")
        else:
            range_score += 0.5
            range_reasons.append("trend direction neutral")

        if htf_aligned > 0:
            trend_score += 0.5 * htf_aligned
            trend_reasons.append(f"htf aligned count {htf_aligned}")
        if htf_conflicting > 0:
            trend_score = max(trend_score - 0.45 * htf_conflicting, 0.0)
            range_score += 0.25 * htf_conflicting
            range_reasons.append(f"htf conflicting count {htf_conflicting}")

        if result.chop and result.chop.is_chop:
            range_score += 0.3
            volatility_score += 0.4
            if result.chop.score >= 0.75:
                volatility_score += 0.3
                volatility_reasons.append(
                    f"chop score {result.chop.score:.2f} indicates unstable tape"
                )

        if (
            volatility_score >= MarketRegime.VOLATILITY_SCORE_TRIGGER
            and trend_score < MarketRegime.VOLATILITY_TREND_CAP
        ):
            regime = MarketRegime.VOLATILE
            reasons = volatility_reasons or ["elevated volatility cluster"]
        elif trend_score >= 2.2 and trend_score >= range_score + 0.45:
            regime = MarketRegime.TRENDING
            reasons = trend_reasons or ["trend score dominant"]
        elif range_score >= 1.6:
            regime = MarketRegime.RANGING
            reasons = range_reasons or ["range score dominant"]
        elif trend_score > range_score and htf_aligned > 0:
            regime = MarketRegime.TRENDING
            reasons = trend_reasons or ["trend score slightly dominant with HTF support"]
        else:
            regime = MarketRegime.RANGING
            reasons = range_reasons or ["fallback to ranging for safety"]

        assessment = RegimeAssessment(
            regime=regime,
            trend_score=trend_score,
            range_score=range_score,
            volatility_score=volatility_score,
            metrics=metrics,
            reasons=reasons,
        )
        return MarketRegime._apply_hysteresis(result, assessment, adx=adx)

    @staticmethod
    def detect(
        result: AnalysisResult,
        full: FullAnalysis | None = None,
    ) -> str:
        """Return the classified market regime."""
        return MarketRegime.assess(result, full=full).regime


@dataclass
class TradeSignal:
    """
    單一交易信號，對應資料庫 signals 表。
    """
    symbol: str
    timeframe: str
    signal_type: str  # "LONG" | "SHORT" | "CLOSE"
    strength: float  # 0.0 ~ 1.0
    strategy_name: str
    indicators: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_db_row(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "signal_type": self.signal_type,
            "strength": self.strength,
            "strategy_name": self.strategy_name,
            "indicators": self.indicators,
        }


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""

    # 子類覆寫: 這個策略適用哪些市場狀態
    allowed_regimes: list[str] = [MarketRegime.TRENDING, MarketRegime.RANGING]

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def evaluate_single(
        self,
        symbol: str,
        timeframe: str,
        result: AnalysisResult,
    ) -> list[TradeSignal]:
        ...

    def evaluate_full(
        self,
        full: FullAnalysis,
        primary_tf: str | None = None,
    ) -> list[TradeSignal]:
        """
        根據完整 MTF 分析結果產生信號。

        v3 改版：
        1. 市場狀態檢查：策略只在允許的狀態下出信號
        2. MTF 方向過濾：信號必須與多時間框架推薦方向一致
        3. HTF RSI 確認
        """
        tf = primary_tf or full.primary_tf
        single = full.single_tf_results.get(tf)
        if not single:
            return []

        # --- 市場狀態檢查 ---
        regime_assessment = MarketRegime.assess(single, full=full)
        regime = regime_assessment.regime
        if regime != MarketRegime.UNKNOWN and regime not in self.allowed_regimes:
            logger.debug(
                f"{self.name} 跳過: 市場狀態 {regime} 不在允許範圍 {self.allowed_regimes}"
            )
            return []

        _preferred_regime = self.allowed_regimes[0] if self.allowed_regimes else None
        _in_non_preferred_regime = (
            regime != MarketRegime.UNKNOWN
            and _preferred_regime is not None
            and regime != _preferred_regime
        )

        signals = self.evaluate_single(full.symbol, tf, single)
        if not signals:
            return signals

        if _in_non_preferred_regime and signals:
            for sig in signals:
                sig.strength = round(sig.strength * 0.7, 4)
                sig.indicators["regime_penalty"] = True
            logger.debug(
                f"{self.name} running in non-preferred regime {regime}, "
                f"strength scaled by 0.7"
            )

        is_ranging_only = self.allowed_regimes == [MarketRegime.RANGING]

        if not is_ranging_only:
            if full.mtf is None or full.mtf.recommended_direction is None:
                logger.info(
                    f"MTF_GATE_BLOCK: {full.symbol} no recommended direction"
                )
                return []

        # --- MTF 方向過濾 ---
        mtf_direction = None
        mtf_confidence = 0.0
        if full.mtf and full.mtf.recommended_direction:
            mtf_direction = full.mtf.recommended_direction
            mtf_confidence = full.mtf.confidence

        if (not is_ranging_only) and full.mtf and full.mtf.confidence < 1.0:
            for sig in signals:
                sig.strength = round(sig.strength * full.mtf.confidence, 4)
                sig.indicators["mtf_confidence_scaled"] = full.mtf.confidence

        htf_rsi_ok = full.htf_rsi_confirmed

        filtered: list[TradeSignal] = []
        for sig in signals:
            # MTF 方向不一致 → 過濾
            if (not is_ranging_only) and mtf_direction is not None and sig.signal_type != mtf_direction:
                logger.debug(
                    f"MTF 過濾: {sig.symbol} {sig.signal_type} "
                    f"(MTF={mtf_direction}, conf={mtf_confidence:.0%})"
                )
                continue

            # HTF RSI 極端 → 過濾
            if not htf_rsi_ok:
                logger.debug(
                    f"HTF RSI 過濾: {sig.symbol} {sig.signal_type}"
                )
                continue

            # MTF 一致 → 加分
            if (not is_ranging_only) and mtf_direction == sig.signal_type and mtf_confidence > 0.5:
                sig.strength = min(sig.strength + 0.1, 1.0)
                sig.indicators["mtf_aligned"] = True
                sig.indicators["mtf_confidence"] = mtf_confidence

            sig.indicators.update(regime_assessment.to_indicator_payload())
            filtered.append(sig)

        return filtered
