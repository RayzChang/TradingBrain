"""Phase 1 regression tests for the upgraded market-regime classifier."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.analysis.engine import AnalysisResult, FullAnalysis
from core.analysis.multi_timeframe import MTFAnalysis, TimeframeAlignment
from core.analysis.chop_detector import ChopResult
from core.pipeline.veto_engine import VetoEngine
from core.strategy.base import BaseStrategy, MarketRegime, TradeSignal


def _make_result(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    trend: str = "BULLISH",
    adx: float = 28.0,
    adx_pos: float = 32.0,
    adx_neg: float = 14.0,
    bb_width: float = 7.0,
    atr: float = 180.0,
    close: float = 70000.0,
    chop_score: float = 0.2,
    is_chop: bool = False,
) -> AnalysisResult:
    df = pd.DataFrame(
        [
            {
                "open_time": pd.Timestamp("2026-03-10 00:00:00"),
                "open": close * 0.995,
                "high": close * 1.003,
                "low": close * 0.992,
                "close": close,
                "volume": 1000.0,
                "adx": adx,
                "adx_pos": adx_pos,
                "adx_neg": adx_neg,
                "bb_width": bb_width,
                "atr": atr,
                "rsi": 55.0,
                "ema_21": close * 0.99,
                "ema_50": close * 0.97,
            }
        ]
    )
    return AnalysisResult(
        symbol=symbol,
        timeframe=timeframe,
        indicators={
            "trend": trend,
            "adx": round(adx, 2),
            "adx_pos": round(adx_pos, 2),
            "adx_neg": round(adx_neg, 2),
            "bb_width": round(bb_width, 4),
            "atr": round(atr, 4),
            "atr_ratio": round(atr / close, 6),
            "close": close,
        },
        chop=ChopResult(
            is_chop=is_chop,
            score=chop_score,
            reasons=["test chop"] if is_chop else [],
            cooldown_minutes=30 if is_chop else 0,
        ),
        df_enriched=df,
    )


def _make_sequence_result(
    *,
    open_time: str,
    trend: str = "BULLISH",
    adx: float = 28.0,
    adx_pos: float = 32.0,
    adx_neg: float = 14.0,
    bb_width: float = 7.0,
    atr: float = 180.0,
    close: float = 70000.0,
    chop_score: float = 0.2,
    is_chop: bool = False,
) -> AnalysisResult:
    result = _make_result(
        trend=trend,
        adx=adx,
        adx_pos=adx_pos,
        adx_neg=adx_neg,
        bb_width=bb_width,
        atr=atr,
        close=close,
        chop_score=chop_score,
        is_chop=is_chop,
    )
    result.df_enriched.loc[result.df_enriched.index[-1], "open_time"] = pd.Timestamp(open_time)
    return result


class DummyTrendStrategy(BaseStrategy):
    allowed_regimes = [MarketRegime.TRENDING]

    @property
    def name(self) -> str:
        return "dummy_trend"

    def evaluate_single(self, symbol: str, timeframe: str, result: AnalysisResult):
        return [
            TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type="LONG",
                strength=0.5,
                strategy_name=self.name,
                indicators={},
                reason="dummy",
            )
        ]


def test_market_regime_classifies_trending_with_htf_support():
    MarketRegime.reset_hysteresis()
    primary = _make_result()
    one_hour = _make_result(timeframe="1h", trend="BULLISH", close=70100.0)
    four_hour = _make_result(timeframe="4h", trend="BULLISH", close=70500.0)
    full = FullAnalysis(
        symbol="BTCUSDT",
        primary_tf="15m",
        single_tf_results={"15m": primary, "1h": one_hour, "4h": four_hour},
    )

    assessment = MarketRegime.assess(primary, full=full)

    assert assessment.regime == MarketRegime.TRENDING
    assert assessment.metrics["htf_aligned"] == 2
    assert assessment.trend_score > assessment.range_score


def test_market_regime_classifies_ranging_when_adx_and_width_are_low():
    MarketRegime.reset_hysteresis()
    result = _make_result(
        trend="NEUTRAL",
        adx=14.0,
        adx_pos=18.0,
        adx_neg=16.5,
        bb_width=3.2,
        atr=90.0,
        close=70000.0,
    )

    assessment = MarketRegime.assess(result)

    assert assessment.regime == MarketRegime.RANGING
    assert assessment.range_score >= 1.6


def test_market_regime_classifies_volatile_when_volatility_is_extreme():
    MarketRegime.reset_hysteresis()
    result = _make_result(
        trend="NEUTRAL",
        adx=16.0,
        adx_pos=21.0,
        adx_neg=20.0,
        bb_width=14.5,
        atr=2600.0,
        close=70000.0,
        chop_score=0.82,
        is_chop=True,
    )

    assessment = MarketRegime.assess(result)

    assert assessment.regime == MarketRegime.VOLATILE
    assert assessment.volatility_score >= 1.6


def test_base_strategy_attaches_regime_payload_to_signal():
    MarketRegime.reset_hysteresis()
    primary = _make_result()
    one_hour = _make_result(timeframe="1h", trend="BULLISH", close=70100.0)
    four_hour = _make_result(timeframe="4h", trend="BULLISH", close=70500.0)
    full = FullAnalysis(
        symbol="BTCUSDT",
        primary_tf="15m",
        single_tf_results={"15m": primary, "1h": one_hour, "4h": four_hour},
        mtf=MTFAnalysis(
            alignment=TimeframeAlignment.ALIGNED_BULLISH,
            details={"4h": "BULLISH", "1h": "BULLISH", "15m": "BULLISH"},
            confidence=1.0,
            recommended_direction="LONG",
        ),
        htf_rsi_confirmed=True,
    )

    strategy = DummyTrendStrategy()
    signals = strategy.evaluate_full(full)

    assert len(signals) == 1
    assert signals[0].indicators["market_regime"] == MarketRegime.TRENDING
    assert "regime_scores" in signals[0].indicators
    assert "regime_metrics" in signals[0].indicators


def test_veto_engine_blocks_volatile_regime():
    MarketRegime.reset_hysteresis()
    db = MagicMock()
    db.get_risk_params.return_value = {}

    funding = MagicMock()
    funding.get_rate.return_value = None

    fear_greed = MagicMock()
    fear_greed.get_value.return_value = None

    liquidation = MagicMock()
    liquidation.is_surge = False

    veto = VetoEngine(
        db=db,
        funding_monitor=funding,
        fear_greed_monitor=fear_greed,
        liquidation_monitor=liquidation,
    )
    result = veto.evaluate(
        "BTCUSDT",
        "LONG",
        market_regime=MarketRegime.VOLATILE,
        regime_details={"scores": {"volatile": 2.1}},
    )

    assert result.vetoed is True
    assert any("volatile" in reason for reason in result.reasons)


def test_market_regime_holds_trending_until_adx_drops_below_buffer():
    MarketRegime.reset_hysteresis()

    trending = _make_sequence_result(
        open_time="2026-03-10 00:00:00",
        trend="BULLISH",
        adx=24.0,
        adx_pos=30.0,
        adx_neg=14.0,
        bb_width=6.0,
        atr=210.0,
        close=70000.0,
    )
    ranging_borderline = _make_sequence_result(
        open_time="2026-03-10 00:15:00",
        trend="NEUTRAL",
        adx=19.0,
        adx_pos=18.0,
        adx_neg=15.5,
        bb_width=3.8,
        atr=120.0,
        close=70000.0,
    )

    first = MarketRegime.assess(trending)
    second = MarketRegime.assess(ranging_borderline)

    assert first.regime == MarketRegime.TRENDING
    assert second.regime == MarketRegime.TRENDING
    assert any("adx < 18" in reason for reason in second.reasons)


def test_market_regime_requires_three_bars_before_switching():
    MarketRegime.reset_hysteresis()

    bar0 = _make_sequence_result(
        open_time="2026-03-10 00:00:00",
        trend="BULLISH",
        adx=26.0,
        adx_pos=33.0,
        adx_neg=13.0,
        bb_width=6.5,
        atr=220.0,
        close=70000.0,
    )
    hold1 = _make_sequence_result(
        open_time="2026-03-10 00:15:00",
        trend="NEUTRAL",
        adx=14.0,
        adx_pos=18.0,
        adx_neg=16.5,
        bb_width=3.0,
        atr=90.0,
        close=70000.0,
    )
    hold2 = _make_sequence_result(
        open_time="2026-03-10 00:30:00",
        trend="NEUTRAL",
        adx=13.5,
        adx_pos=17.5,
        adx_neg=16.8,
        bb_width=3.1,
        atr=88.0,
        close=70000.0,
    )
    switch_ok = _make_sequence_result(
        open_time="2026-03-10 00:45:00",
        trend="NEUTRAL",
        adx=13.0,
        adx_pos=17.0,
        adx_neg=16.9,
        bb_width=3.2,
        atr=86.0,
        close=70000.0,
    )

    assert MarketRegime.assess(bar0).regime == MarketRegime.TRENDING
    assert MarketRegime.assess(hold1).regime == MarketRegime.TRENDING
    assert MarketRegime.assess(hold2).regime == MarketRegime.TRENDING
    final = MarketRegime.assess(switch_ok)
    assert final.regime == MarketRegime.RANGING
    assert any("switch accepted" in reason for reason in final.reasons)
