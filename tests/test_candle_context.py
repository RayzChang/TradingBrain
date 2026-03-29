"""Tests for core.analysis.candle_context module."""

import pandas as pd
import pytest

from core.analysis.candle_context import CandleContext, analyze_candle_context


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """Helper to build OHLCV DataFrame from row dicts."""
    return pd.DataFrame(rows)


class TestAnalyzeCandleContext:
    """Test suite for analyze_candle_context()."""

    def test_empty_df_returns_neutral(self):
        df = pd.DataFrame(columns=["open", "high", "low", "close"])
        ctx = analyze_candle_context(df)
        assert ctx.momentum_score == 0.0
        assert ctx.dominant_direction == "neutral"
        assert ctx.body_progression == "mixed"

    def test_none_df_returns_neutral(self):
        ctx = analyze_candle_context(None)
        assert ctx.dominant_direction == "neutral"

    def test_single_row_returns_neutral(self):
        df = _make_df([{"open": 100, "high": 105, "low": 95, "close": 103}])
        ctx = analyze_candle_context(df)
        assert ctx.dominant_direction == "neutral"

    def test_strong_bullish_momentum(self):
        """8 consecutive bullish candles with growing bodies → bullish."""
        rows = []
        base = 100.0
        for i in range(8):
            o = base + i * 2
            c = o + 1.5 + i * 0.3  # growing bodies
            rows.append({"open": o, "high": c + 0.2, "low": o - 0.2, "close": c})
        df = _make_df(rows)
        ctx = analyze_candle_context(df)
        assert ctx.momentum_score > 0.3
        assert ctx.dominant_direction == "bullish"
        assert ctx.body_progression == "growing"

    def test_strong_bearish_momentum(self):
        """8 consecutive bearish candles → bearish."""
        rows = []
        base = 200.0
        for i in range(8):
            o = base - i * 2
            c = o - 1.5 - i * 0.3
            rows.append({"open": o, "high": o + 0.2, "low": c - 0.2, "close": c})
        df = _make_df(rows)
        ctx = analyze_candle_context(df)
        assert ctx.momentum_score < -0.3
        assert ctx.dominant_direction == "bearish"

    def test_mixed_direction_is_neutral(self):
        """Alternating bullish/bearish → neutral."""
        rows = []
        for i in range(8):
            if i % 2 == 0:
                rows.append({"open": 100, "high": 102, "low": 99, "close": 101})
            else:
                rows.append({"open": 101, "high": 102, "low": 99, "close": 100})
        df = _make_df(rows)
        ctx = analyze_candle_context(df)
        assert ctx.dominant_direction == "neutral"
        assert abs(ctx.momentum_score) < 0.3

    def test_shrinking_bodies(self):
        """Bodies get smaller over time → shrinking."""
        rows = []
        for i in range(8):
            body_size = 5.0 - i * 0.5  # 5.0 → 1.5
            o = 100.0
            c = o + max(body_size, 0.3)
            rows.append({"open": o, "high": c + 0.5, "low": o - 0.5, "close": c})
        df = _make_df(rows)
        ctx = analyze_candle_context(df)
        assert ctx.body_progression == "shrinking"

    def test_volume_rising(self):
        """Volume increases in second half → rising."""
        rows = []
        for i in range(8):
            vol = 100 if i < 4 else 200
            rows.append({
                "open": 100, "high": 102, "low": 99, "close": 101,
                "volume": vol,
            })
        df = _make_df(rows)
        ctx = analyze_candle_context(df)
        assert ctx.volume_trend == "rising"

    def test_volume_falling(self):
        """Volume decreases in second half → falling."""
        rows = []
        for i in range(8):
            vol = 200 if i < 4 else 80
            rows.append({
                "open": 100, "high": 102, "low": 99, "close": 101,
                "volume": vol,
            })
        df = _make_df(rows)
        ctx = analyze_candle_context(df)
        assert ctx.volume_trend == "falling"

    def test_no_volume_column(self):
        """No volume column → volume_trend is flat."""
        rows = [{"open": 100, "high": 102, "low": 99, "close": 101} for _ in range(8)]
        df = _make_df(rows)
        ctx = analyze_candle_context(df)
        assert ctx.volume_trend == "flat"

    def test_rejection_count_lower_wick(self):
        """Candles with long lower wicks at similar lows → rejection counted."""
        rows = []
        for _ in range(4):
            # Long lower wick: body at top, wick reaching down to 95
            rows.append({"open": 100, "high": 101, "low": 95, "close": 101})
        df = _make_df(rows)
        ctx = analyze_candle_context(df)
        assert ctx.rejection_count >= 2

    def test_custom_lookback(self):
        """Only last N candles are analyzed."""
        rows = []
        # First 10: bearish
        for _ in range(10):
            rows.append({"open": 100, "high": 101, "low": 97, "close": 98})
        # Last 4: bullish
        for _ in range(4):
            rows.append({"open": 100, "high": 104, "low": 99, "close": 103})
        df = _make_df(rows)
        ctx = analyze_candle_context(df, lookback=4)
        assert ctx.momentum_score > 0
        assert ctx.dominant_direction == "bullish"

    def test_returns_dataclass(self):
        rows = [{"open": 100, "high": 102, "low": 99, "close": 101} for _ in range(4)]
        df = _make_df(rows)
        ctx = analyze_candle_context(df)
        assert isinstance(ctx, CandleContext)
        assert isinstance(ctx.momentum_score, float)
        assert isinstance(ctx.rejection_count, int)
        assert ctx.body_progression in ("growing", "shrinking", "mixed")
        assert ctx.volume_trend in ("rising", "falling", "flat")
        assert ctx.dominant_direction in ("bullish", "bearish", "neutral")
