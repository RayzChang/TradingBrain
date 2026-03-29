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
    confidence: float = 0.8


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


def test_trend_following_long_requires_pullback_rejection_continuation() -> None:
    df = pd.DataFrame(
        [
            {"open": 100.0, "high": 101.0, "low": 99.2, "close": 100.2, "ema_9": 99.6, "ema_21": 99.8, "ema_50": 98.7, "adx": 24, "adx_pos": 22, "adx_neg": 16, "rsi": 53, "macd_hist": 0.12},
            {"open": 100.4, "high": 102.6, "low": 100.1, "close": 102.2, "ema_9": 100.9, "ema_21": 100.2, "ema_50": 99.0, "adx": 26, "adx_pos": 24, "adx_neg": 15, "rsi": 56, "macd_hist": 0.18},
            {"open": 102.0, "high": 102.4, "low": 101.0, "close": 101.4, "ema_9": 101.2, "ema_21": 100.7, "ema_50": 99.4, "adx": 27, "adx_pos": 24, "adx_neg": 14, "rsi": 55, "macd_hist": 0.17},
            {"open": 101.3, "high": 103.5, "low": 100.8, "close": 103.0, "ema_9": 102.0, "ema_21": 101.0, "ema_50": 99.8, "adx": 30, "adx_pos": 28, "adx_neg": 13, "rsi": 59, "macd_hist": 0.24},
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
    assert signals[0].indicators["pullback_to_ema21"] is True
    assert signals[0].indicators["rejection_candle"] is True
    assert signals[0].indicators["continuation_break_confirmed"] is True


def test_trend_following_long_rejects_extension_without_pullback() -> None:
    df = pd.DataFrame(
        [
            {"open": 101.8, "high": 102.2, "low": 101.9, "close": 102.1, "ema_9": 99.8, "ema_21": 99.7, "ema_50": 98.9, "adx": 24, "adx_pos": 22, "adx_neg": 17, "rsi": 54, "macd_hist": 0.10},
            {"open": 101.0, "high": 103.0, "low": 102.1, "close": 102.6, "ema_9": 101.0, "ema_21": 100.2, "ema_50": 99.2, "adx": 26, "adx_pos": 24, "adx_neg": 16, "rsi": 57, "macd_hist": 0.18},
            {"open": 102.5, "high": 104.0, "low": 102.4, "close": 103.7, "ema_9": 102.3, "ema_21": 100.9, "ema_50": 99.5, "adx": 27, "adx_pos": 25, "adx_neg": 15, "rsi": 59, "macd_hist": 0.21},
            {"open": 103.6, "high": 105.0, "low": 103.5, "close": 104.8, "ema_9": 103.4, "ema_21": 101.2, "ema_50": 99.9, "adx": 29, "adx_pos": 27, "adx_neg": 14, "rsi": 61, "macd_hist": 0.25},
        ]
    )
    strategy = TrendFollowingStrategy(adx_min=20, skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(df, [_DummyPattern(PatternDirection.BULLISH)]),
    )

    assert signals == []


def test_trend_following_short_requires_bounce_failure_and_breakdown() -> None:
    df = pd.DataFrame(
        [
            {"open": 105.0, "high": 105.4, "low": 103.8, "close": 104.2, "ema_9": 104.8, "ema_21": 105.2, "ema_50": 106.4, "adx": 24, "adx_pos": 15, "adx_neg": 22, "rsi": 48, "macd_hist": -0.12},
            {"open": 104.0, "high": 104.2, "low": 102.0, "close": 102.5, "ema_9": 103.6, "ema_21": 104.7, "ema_50": 106.0, "adx": 26, "adx_pos": 14, "adx_neg": 24, "rsi": 43, "macd_hist": -0.18},
            {"open": 102.6, "high": 104.5, "low": 102.4, "close": 103.8, "ema_9": 103.4, "ema_21": 104.0, "ema_50": 105.4, "adx": 27, "adx_pos": 14, "adx_neg": 24, "rsi": 46, "macd_hist": -0.16},
            {"open": 103.9, "high": 104.8, "low": 101.4, "close": 101.8, "ema_9": 102.7, "ema_21": 103.6, "ema_50": 104.8, "adx": 30, "adx_pos": 13, "adx_neg": 28, "rsi": 41, "macd_hist": -0.24},
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
    assert signals[0].indicators["pullback_to_ema21"] is True
    assert signals[0].indicators["rejection_candle"] is True
    assert signals[0].indicators["continuation_break_confirmed"] is True


def test_trend_following_short_rejects_breakdown_without_bounce_failure() -> None:
    """No short when candle shape lacks upper wick AND candle context momentum is neutral."""
    df = pd.DataFrame(
        [
            # Mixed candles: alternating bullish/bearish so momentum ~0 (no candle_context confirm)
            {"open": 104.0, "high": 105.0, "low": 103.5, "close": 104.8, "ema_9": 104.9, "ema_21": 105.3, "ema_50": 106.4, "adx": 24, "adx_pos": 15, "adx_neg": 22, "rsi": 48, "macd_hist": -0.12},
            {"open": 104.8, "high": 105.2, "low": 103.0, "close": 103.5, "ema_9": 103.8, "ema_21": 104.8, "ema_50": 106.0, "adx": 26, "adx_pos": 14, "adx_neg": 24, "rsi": 43, "macd_hist": -0.18},
            {"open": 103.0, "high": 105.0, "low": 102.5, "close": 104.8, "ema_9": 103.0, "ema_21": 104.0, "ema_50": 105.4, "adx": 27, "adx_pos": 14, "adx_neg": 24, "rsi": 42, "macd_hist": -0.20},
            # Last candle: bearish but no upper wick (straight drop, no bounce failure)
            {"open": 101.9, "high": 102.1, "low": 100.9, "close": 101.0, "ema_9": 102.2, "ema_21": 103.5, "ema_50": 104.8, "adx": 30, "adx_pos": 13, "adx_neg": 28, "rsi": 36, "macd_hist": -0.24},
        ]
    )
    strategy = TrendFollowingStrategy(adx_min=20, skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(df),
    )

    assert signals == []


def test_trend_following_long_filters_when_too_close_to_upper_band(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "core.strategy.trend_following.logger.info",
        lambda message: messages.append(message),
    )
    df = pd.DataFrame(
        [
            {"open": 100.0, "high": 101.0, "low": 99.2, "close": 100.2, "ema_9": 99.6, "ema_21": 99.8, "ema_50": 98.7, "adx": 24, "adx_pos": 22, "adx_neg": 16, "rsi": 53, "macd_hist": 0.12, "bb_pct": 0.55},
            {"open": 100.4, "high": 102.6, "low": 100.1, "close": 102.2, "ema_9": 100.9, "ema_21": 100.2, "ema_50": 99.0, "adx": 26, "adx_pos": 24, "adx_neg": 15, "rsi": 56, "macd_hist": 0.18, "bb_pct": 0.70},
            {"open": 102.0, "high": 102.4, "low": 101.0, "close": 101.4, "ema_9": 101.2, "ema_21": 100.7, "ema_50": 99.4, "adx": 27, "adx_pos": 24, "adx_neg": 14, "rsi": 55, "macd_hist": 0.17, "bb_pct": 0.76},
            {"open": 101.3, "high": 103.5, "low": 100.8, "close": 103.0, "ema_9": 102.0, "ema_21": 101.0, "ema_50": 99.8, "adx": 30, "adx_pos": 28, "adx_neg": 13, "rsi": 59, "macd_hist": 0.24, "bb_pct": 0.91},
        ]
    )
    strategy = TrendFollowingStrategy(adx_min=20, skip_on_chop=False)

    signals = strategy.evaluate_single(
        "BTCUSDT",
        "15m",
        _make_result(df, [_DummyPattern(PatternDirection.BULLISH)]),
    )

    assert signals == []
    assert any("ENTRY_QUALITY_FILTER: BTCUSDT LONG_bb_position_0.91_above_0.85" in msg for msg in messages)
