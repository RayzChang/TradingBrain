import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.analysis.candlestick import PatternDirection
from core.analysis.engine import AnalysisResult
from core.strategy.mean_reversion import MeanReversionStrategy


@dataclass
class _DummyChop:
    is_chop: bool = False


@dataclass
class _DummyPattern:
    direction: PatternDirection
    confidence: float = 0.8


def _make_result(
    df: pd.DataFrame,
    *,
    rsi: float,
    bb_pct: float,
    candle_patterns: list | None = None,
) -> AnalysisResult:
    return AnalysisResult(
        symbol="BTCUSDT",
        timeframe="15m",
        indicators={"rsi": rsi, "bb_pct": bb_pct},
        divergences=[],
        fibonacci={"available": False},
        candle_patterns=candle_patterns or [],
        chop=_DummyChop(False),
        df_enriched=df,
    )


def test_mean_reversion_short_requires_true_range_edge_reversal() -> None:
    df = pd.DataFrame(
        [
            {"open": 100.0, "high": 109.5, "low": 99.5, "close": 108.6, "bb_upper": 109.0, "bb_lower": 99.0},
            {"open": 108.5, "high": 109.8, "low": 106.8, "close": 108.2, "bb_upper": 109.2, "bb_lower": 99.2},
            {"open": 108.1, "high": 110.0, "low": 107.2, "close": 107.5, "bb_upper": 109.3, "bb_lower": 99.5},
            {"open": 109.0, "high": 110.2, "low": 106.4, "close": 107.2, "bb_upper": 109.0, "bb_lower": 99.8},
        ]
    )
    strategy = MeanReversionStrategy(skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(
            df,
            rsi=78,
            bb_pct=0.99,
            candle_patterns=[_DummyPattern(PatternDirection.BEARISH)],
        ),
    )

    assert len(signals) == 1
    assert signals[0].signal_type == "SHORT"
    assert signals[0].indicators["near_range_high"] is True
    assert signals[0].indicators["bearish_reversal"] is True


def test_mean_reversion_short_rejects_if_not_near_real_range_high() -> None:
    df = pd.DataFrame(
        [
            {"open": 100.0, "high": 110.0, "low": 99.5, "close": 108.5, "bb_upper": 110.2, "bb_lower": 99.0},
            {"open": 108.4, "high": 109.0, "low": 106.5, "close": 107.2, "bb_upper": 109.8, "bb_lower": 99.4},
            {"open": 107.1, "high": 107.8, "low": 105.4, "close": 106.0, "bb_upper": 109.4, "bb_lower": 99.7},
            {"open": 106.4, "high": 107.0, "low": 104.8, "close": 105.2, "bb_upper": 109.0, "bb_lower": 100.0},
        ]
    )
    strategy = MeanReversionStrategy(skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(
            df,
            rsi=76,
            bb_pct=0.96,
            candle_patterns=[_DummyPattern(PatternDirection.BEARISH)],
        ),
    )

    assert signals == []


def test_mean_reversion_long_requires_range_low_reclaim() -> None:
    df = pd.DataFrame(
        [
            {"open": 110.0, "high": 110.4, "low": 100.1, "close": 101.2, "bb_upper": 110.8, "bb_lower": 100.4},
            {"open": 101.1, "high": 103.2, "low": 100.0, "close": 102.2, "bb_upper": 110.5, "bb_lower": 100.2},
            {"open": 102.0, "high": 102.4, "low": 99.8, "close": 100.8, "bb_upper": 110.3, "bb_lower": 100.0},
            {"open": 100.4, "high": 103.0, "low": 99.2, "close": 101.9, "bb_upper": 110.1, "bb_lower": 100.1},
        ]
    )
    strategy = MeanReversionStrategy(skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(
            df,
            rsi=31,
            bb_pct=0.07,
            candle_patterns=[_DummyPattern(PatternDirection.BULLISH)],
        ),
    )

    assert len(signals) == 1
    assert signals[0].signal_type == "LONG"
    assert signals[0].indicators["near_range_low"] is True
    assert signals[0].indicators["bullish_reversal"] is True
