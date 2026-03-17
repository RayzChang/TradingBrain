"""Phase 3 tests for strict four-layer MTF gating."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.analysis.engine import AnalysisResult, FullAnalysis
from core.analysis.multi_timeframe import (
    MTFAnalysis,
    TimeframeAlignment,
    analyze_multi_timeframe,
)
from core.analysis.chop_detector import ChopResult
from core.strategy.base import BaseStrategy, MarketRegime, TradeSignal


def _make_tf_df(trend: str) -> pd.DataFrame:
    df = pd.DataFrame([{"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 10.0}] * 60)
    df.attrs["trend"] = trend
    return df


def _make_result(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    trend: str = "BULLISH",
) -> AnalysisResult:
    close = 100.0
    df = pd.DataFrame(
        [
            {
                "open_time": pd.Timestamp("2026-03-14 00:00:00"),
                "open": 99.0,
                "high": 101.0,
                "low": 98.0,
                "close": close,
                "volume": 1000.0,
                "adx": 28.0,
                "adx_pos": 30.0,
                "adx_neg": 14.0,
                "bb_width": 6.0,
                "atr": 1.2,
                "rsi": 55.0,
                "ema_21": 99.0,
                "ema_50": 97.0,
            }
        ]
    )
    return AnalysisResult(
        symbol=symbol,
        timeframe=timeframe,
        indicators={
            "trend": trend,
            "adx": 28.0,
            "adx_pos": 30.0,
            "adx_neg": 14.0,
            "bb_width": 6.0,
            "atr": 1.2,
            "atr_ratio": 0.012,
            "close": close,
        },
        chop=ChopResult(is_chop=False, score=0.2, reasons=[], cooldown_minutes=0),
        df_enriched=df,
    )


class DummyTrendStrategy(BaseStrategy):
    allowed_regimes = [MarketRegime.TRENDING]

    @property
    def name(self) -> str:
        return "dummy_phase3"

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


def test_analyze_multi_timeframe_ignores_15m_in_direction_vote():
    with patch("core.analysis.multi_timeframe.add_all_indicators", side_effect=lambda df: df), patch(
        "core.analysis.multi_timeframe.get_trend_direction",
        side_effect=lambda df: df.attrs["trend"],
    ):
        analysis = analyze_multi_timeframe(
            {
                "4h": _make_tf_df("BULLISH"),
                "1h": _make_tf_df("BULLISH"),
                "15m": _make_tf_df("BEARISH"),
            }
        )

    assert analysis.recommended_direction == "LONG"
    assert analysis.alignment == TimeframeAlignment.ALIGNED_BULLISH
    assert analysis.details["15m"] == "BEARISH"


def test_analyze_multi_timeframe_returns_none_when_4h_and_1h_conflict():
    with patch("core.analysis.multi_timeframe.add_all_indicators", side_effect=lambda df: df), patch(
        "core.analysis.multi_timeframe.get_trend_direction",
        side_effect=lambda df: df.attrs["trend"],
    ):
        analysis = analyze_multi_timeframe(
            {
                "4h": _make_tf_df("BULLISH"),
                "1h": _make_tf_df("BEARISH"),
                "15m": _make_tf_df("BULLISH"),
            }
        )

    assert analysis.recommended_direction is None
    assert analysis.alignment == TimeframeAlignment.CONFLICTING


def test_base_strategy_blocks_when_4h_direction_is_not_explicit():
    strategy = DummyTrendStrategy()
    primary = _make_result()
    full = FullAnalysis(
        symbol="BTCUSDT",
        primary_tf="15m",
        single_tf_results={"15m": primary},
        mtf=MTFAnalysis(
            alignment=TimeframeAlignment.CONFLICTING,
            details={"4h": "NEUTRAL", "1h": "BULLISH", "15m": "BULLISH"},
            confidence=0.0,
            recommended_direction=None,
        ),
        htf_rsi_confirmed=True,
    )

    signals = strategy.evaluate_full(full)

    assert signals == []


def test_base_strategy_blocks_when_recommended_direction_is_missing():
    strategy = DummyTrendStrategy()
    primary = _make_result()
    full = FullAnalysis(
        symbol="BTCUSDT",
        primary_tf="15m",
        single_tf_results={"15m": primary},
        mtf=MTFAnalysis(
            alignment=TimeframeAlignment.CONFLICTING,
            details={"4h": "BULLISH", "1h": "BULLISH", "15m": "BULLISH"},
            confidence=0.0,
            recommended_direction=None,
        ),
        htf_rsi_confirmed=True,
    )

    signals = strategy.evaluate_full(full)

    assert signals == []
