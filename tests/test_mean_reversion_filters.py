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


def test_mean_reversion_short_requires_bearish_reversal() -> None:
    df = pd.DataFrame(
        [
            {"open": 100, "close": 102, "bb_upper": 103, "bb_lower": 97, "ema_21": 100},
            {"open": 102, "close": 104, "bb_upper": 104.5, "bb_lower": 98, "ema_21": 101},
        ]
    )
    strategy = MeanReversionStrategy(skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(df, rsi=78, bb_pct=0.98),
    )

    assert signals == []


def test_mean_reversion_short_survives_with_bearish_reversal() -> None:
    df = pd.DataFrame(
        [
            {"open": 100, "close": 102, "bb_upper": 103, "bb_lower": 97, "ema_21": 101},
            {"open": 104, "close": 100.5, "bb_upper": 101, "bb_lower": 96, "ema_21": 101},
        ]
    )
    strategy = MeanReversionStrategy(skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(
            df,
            rsi=79,
            bb_pct=0.99,
            candle_patterns=[_DummyPattern(PatternDirection.BEARISH)],
        ),
    )

    assert len(signals) == 1
    assert signals[0].signal_type == "SHORT"
    assert signals[0].indicators["bearish_reversal"] is True
