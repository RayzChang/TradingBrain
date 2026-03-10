import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.analysis.candlestick import PatternDirection
from core.analysis.engine import AnalysisResult
from core.strategy.trend_following import TrendFollowingStrategy


@dataclass
class _DummyChop:
    is_chop: bool = False


@dataclass
class _DummyPattern:
    direction: PatternDirection


def _make_result(df: pd.DataFrame, candle_patterns: list | None = None) -> AnalysisResult:
    return AnalysisResult(
        symbol="BTCUSDT",
        timeframe="15m",
        indicators={"trend": "BULLISH"},
        divergences=[],
        fibonacci={"available": False},
        candle_patterns=candle_patterns or [],
        chop=_DummyChop(False),
        df_enriched=df,
    )


def test_trend_following_long_requires_bullish_stack() -> None:
    df = pd.DataFrame(
        [
            {"close": 99, "ema_9": 98, "ema_21": 100, "ema_50": 105, "adx": 27, "adx_pos": 17, "adx_neg": 23},
            {"close": 100, "ema_9": 99, "ema_21": 100, "ema_50": 104, "adx": 28, "adx_pos": 18, "adx_neg": 22},
            {"close": 102, "ema_9": 101, "ema_21": 100, "ema_50": 103, "adx": 29, "adx_pos": 19, "adx_neg": 24},
        ]
    )
    strategy = TrendFollowingStrategy(adx_min=20, skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(df, [_DummyPattern(PatternDirection.BULLISH)]),
    )

    assert signals == []


def test_trend_following_long_survives_when_stack_is_confirmed() -> None:
    df = pd.DataFrame(
        [
            {"high": 99, "close": 98, "ema_9": 97, "ema_21": 99, "ema_50": 95, "adx": 27, "adx_pos": 23, "adx_neg": 19, "rsi": 55, "macd_hist": 0.2},
            {"high": 101, "close": 100, "ema_9": 99, "ema_21": 100, "ema_50": 96, "adx": 28, "adx_pos": 24, "adx_neg": 18, "rsi": 57, "macd_hist": 0.25},
            {"high": 105, "close": 104, "ema_9": 102, "ema_21": 101, "ema_50": 97, "adx": 30, "adx_pos": 28, "adx_neg": 16, "rsi": 60, "macd_hist": 0.35},
        ]
    )
    strategy = TrendFollowingStrategy(adx_min=20, skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(df, [_DummyPattern(PatternDirection.BULLISH)]),
    )

    assert len(signals) == 1
    assert signals[0].signal_type == "LONG"
    assert signals[0].indicators["bullish_stack_ok"] is True


def test_trend_following_long_requires_momentum_confirmation() -> None:
    df = pd.DataFrame(
        [
            {"high": 99, "close": 98, "ema_9": 97, "ema_21": 99, "ema_50": 95, "adx": 27, "adx_pos": 23, "adx_neg": 19, "rsi": 55, "macd_hist": 0.2},
            {"high": 101, "close": 100, "ema_9": 99, "ema_21": 100, "ema_50": 96, "adx": 28, "adx_pos": 24, "adx_neg": 18, "rsi": 57, "macd_hist": 0.25},
            {"high": 101, "close": 100.5, "ema_9": 102, "ema_21": 101, "ema_50": 97, "adx": 30, "adx_pos": 28, "adx_neg": 16, "rsi": 74, "macd_hist": 0.1},
        ]
    )
    strategy = TrendFollowingStrategy(adx_min=20, skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(df, [_DummyPattern(PatternDirection.BEARISH)]),
    )

    assert signals == []


def test_trend_following_short_requires_bearish_stack() -> None:
    df = pd.DataFrame(
        [
            {"low": 100, "close": 104, "ema_9": 105, "ema_21": 103, "ema_50": 104, "adx": 27, "adx_pos": 24, "adx_neg": 18, "rsi": 45, "macd_hist": -0.10},
            {"low": 99, "close": 102, "ema_9": 103, "ema_21": 103, "ema_50": 103, "adx": 28, "adx_pos": 23, "adx_neg": 19, "rsi": 44, "macd_hist": -0.12},
            {"low": 97, "close": 98, "ema_9": 101, "ema_21": 102, "ema_50": 103, "adx": 30, "adx_pos": 18, "adx_neg": 25, "rsi": 44, "macd_hist": -0.15},
        ]
    )
    strategy = TrendFollowingStrategy(adx_min=20, skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(df, [_DummyPattern(PatternDirection.BEARISH)]),
    )

    assert len(signals) == 1
    assert signals[0].signal_type == "SHORT"
    assert signals[0].indicators["bearish_stack_ok"] is True


def test_trend_following_short_requires_momentum_confirmation() -> None:
    df = pd.DataFrame(
        [
            {"low": 100, "close": 104, "ema_9": 105, "ema_21": 103, "ema_50": 105, "adx": 27, "adx_pos": 20, "adx_neg": 22, "rsi": 45, "macd_hist": -0.05},
            {"low": 99, "close": 102, "ema_9": 103, "ema_21": 103, "ema_50": 104, "adx": 28, "adx_pos": 19, "adx_neg": 24, "rsi": 43, "macd_hist": -0.08},
            {"low": 101, "close": 101.5, "ema_9": 101, "ema_21": 102, "ema_50": 103, "adx": 30, "adx_pos": 18, "adx_neg": 26, "rsi": 25, "macd_hist": -0.03},
        ]
    )
    strategy = TrendFollowingStrategy(adx_min=20, skip_on_chop=False)

    signals = strategy.evaluate_single("BTCUSDT", "15m", _make_result(df))

    assert signals == []
