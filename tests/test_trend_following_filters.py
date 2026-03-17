import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

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


def test_trend_following_long_filters_bb_position(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "core.strategy.trend_following.logger.info",
        lambda message: messages.append(message),
    )
    df = pd.DataFrame(
        [
            {
                "high": 99,
                "close": 98,
                "ema_9": 97,
                "ema_21": 99,
                "ema_50": 95,
                "adx": 27,
                "adx_pos": 23,
                "adx_neg": 19,
                "rsi": 55,
                "macd_hist": 0.2,
                "bb_pct": 0.55,
            },
            {
                "high": 101,
                "close": 100,
                "ema_9": 99,
                "ema_21": 100,
                "ema_50": 96,
                "adx": 28,
                "adx_pos": 24,
                "adx_neg": 18,
                "rsi": 57,
                "macd_hist": 0.25,
                "bb_pct": 0.65,
            },
            {
                "high": 105,
                "close": 104,
                "ema_9": 102,
                "ema_21": 101,
                "ema_50": 97,
                "adx": 30,
                "adx_pos": 28,
                "adx_neg": 16,
                "rsi": 60,
                "macd_hist": 0.35,
                "bb_pct": 0.90,
            },
        ]
    )
    strategy = TrendFollowingStrategy(adx_min=20, skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(df, [_DummyPattern(PatternDirection.BULLISH)]),
    )

    assert signals == []
    assert any("ENTRY_QUALITY_FILTER: BTCUSDT LONG_bb_position_0.90_above_0.85" in msg for msg in messages)


def test_trend_following_long_filters_high_rsi_near_upper_band(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "core.strategy.trend_following.logger.info",
        lambda message: messages.append(message),
    )
    df = pd.DataFrame(
        [
            {
                "high": 99,
                "close": 98,
                "ema_9": 97,
                "ema_21": 99,
                "ema_50": 95,
                "adx": 27,
                "adx_pos": 23,
                "adx_neg": 19,
                "rsi": 55,
                "macd_hist": 0.2,
                "bb_pct": 0.55,
            },
            {
                "high": 101,
                "close": 100,
                "ema_9": 99,
                "ema_21": 100,
                "ema_50": 96,
                "adx": 28,
                "adx_pos": 24,
                "adx_neg": 18,
                "rsi": 57,
                "macd_hist": 0.25,
                "bb_pct": 0.60,
            },
            {
                "high": 105,
                "close": 104,
                "ema_9": 102,
                "ema_21": 101,
                "ema_50": 97,
                "adx": 30,
                "adx_pos": 28,
                "adx_neg": 16,
                "rsi": 64,
                "macd_hist": 0.35,
                "bb_pct": 0.80,
            },
        ]
    )
    strategy = TrendFollowingStrategy(adx_min=20, skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(df, [_DummyPattern(PatternDirection.BULLISH)]),
    )

    assert signals == []
    assert any(
        "ENTRY_QUALITY_FILTER: BTCUSDT LONG_rsi_64.00_and_bb_position_0.80_above_0.75" in msg
        for msg in messages
    )


def test_trend_following_short_filters_bb_position(monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "core.strategy.trend_following.logger.info",
        lambda message: messages.append(message),
    )
    df = pd.DataFrame(
        [
            {
                "low": 100,
                "close": 104,
                "ema_9": 105,
                "ema_21": 103,
                "ema_50": 105,
                "adx": 27,
                "adx_pos": 20,
                "adx_neg": 22,
                "rsi": 45,
                "macd_hist": -0.05,
                "bb_pct": 0.50,
            },
            {
                "low": 99,
                "close": 102,
                "ema_9": 103,
                "ema_21": 103,
                "ema_50": 104,
                "adx": 28,
                "adx_pos": 19,
                "adx_neg": 24,
                "rsi": 43,
                "macd_hist": -0.08,
                "bb_pct": 0.35,
            },
            {
                "low": 97,
                "close": 98,
                "ema_9": 101,
                "ema_21": 102,
                "ema_50": 103,
                "adx": 30,
                "adx_pos": 18,
                "adx_neg": 26,
                "rsi": 44,
                "macd_hist": -0.15,
                "bb_pct": 0.10,
            },
        ]
    )
    strategy = TrendFollowingStrategy(adx_min=20, skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(df, [_DummyPattern(PatternDirection.BEARISH)]),
    )

    assert signals == []
    assert any("ENTRY_QUALITY_FILTER: BTCUSDT SHORT_bb_position_0.10_below_0.15" in msg for msg in messages)


def test_trend_following_short_filters_low_rsi_near_lower_band(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "core.strategy.trend_following.logger.info",
        lambda message: messages.append(message),
    )
    df = pd.DataFrame(
        [
            {
                "low": 100,
                "close": 104,
                "ema_9": 105,
                "ema_21": 103,
                "ema_50": 105,
                "adx": 27,
                "adx_pos": 20,
                "adx_neg": 22,
                "rsi": 45,
                "macd_hist": -0.05,
                "bb_pct": 0.50,
            },
            {
                "low": 99,
                "close": 102,
                "ema_9": 103,
                "ema_21": 103,
                "ema_50": 104,
                "adx": 28,
                "adx_pos": 19,
                "adx_neg": 24,
                "rsi": 43,
                "macd_hist": -0.08,
                "bb_pct": 0.35,
            },
            {
                "low": 97,
                "close": 98,
                "ema_9": 101,
                "ema_21": 102,
                "ema_50": 103,
                "adx": 30,
                "adx_pos": 18,
                "adx_neg": 26,
                "rsi": 35,
                "macd_hist": -0.15,
                "bb_pct": 0.20,
            },
        ]
    )
    strategy = TrendFollowingStrategy(adx_min=20, skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(df, [_DummyPattern(PatternDirection.BEARISH)]),
    )

    assert signals == []
    assert any(
        "ENTRY_QUALITY_FILTER: BTCUSDT SHORT_rsi_35.00_and_bb_position_0.20_below_0.25" in msg
        for msg in messages
    )


def test_cross_age_filter_detects_stale_bullish_cross() -> None:
    rows = []
    for idx in range(35):
        if idx == 0:
            rows.append({"ema_9": 99.0, "ema_21": 100.0})
        elif idx == 1:
            rows.append({"ema_9": 101.0, "ema_21": 100.0})
        else:
            rows.append({"ema_9": 101.0 + idx * 0.01, "ema_21": 100.0 + idx * 0.005})

    df = pd.DataFrame(rows)
    strategy = TrendFollowingStrategy(skip_on_chop=False)

    assert strategy._get_cross_age_bars(df, bullish=True) == 33
