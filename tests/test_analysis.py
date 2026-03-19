"""
第三階段測試 — 技術分析引擎

驗證所有分析模組:
1. 指標計算
2. 背離偵測
3. 斐波那契
4. K 線型態
5. 多時間框架
6. 絞肉機偵測
7. AnalysisEngine 整合
"""

import numpy as np
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.analysis.indicators import (
    add_all_indicators, get_trend_direction, get_indicator_summary,
)
from core.analysis.divergence import (
    detect_all_divergences, find_swing_highs, find_swing_lows,
)
from core.analysis.fibonacci import calculate_fibonacci, get_fib_summary, find_nearest_fib_levels
from core.analysis.candlestick import detect_all_patterns, get_latest_pattern_signal
from core.analysis.multi_timeframe import analyze_multi_timeframe, get_mtf_summary
from core.analysis.chop_detector import detect_chop, get_chop_summary
from core.analysis.engine import AnalysisEngine


def make_ohlcv(n: int = 200, trend: str = "up") -> pd.DataFrame:
    """產生模擬 OHLCV 數據"""
    np.random.seed(42)
    dates = pd.date_range("2025-01-01", periods=n, freq="15min")

    if trend == "up":
        base = np.cumsum(np.random.randn(n) * 0.5 + 0.1) + 100
    elif trend == "down":
        base = np.cumsum(np.random.randn(n) * 0.5 - 0.1) + 200
    else:
        base = np.random.randn(n) * 0.3 + 100

    noise = np.random.randn(n) * 0.5
    high = base + abs(noise) + np.random.rand(n) * 1.5
    low = base - abs(noise) - np.random.rand(n) * 1.5
    close = base + noise
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.random.rand(n) * 1000 + 100

    return pd.DataFrame({
        "open_time": dates.astype(np.int64) // 10**6,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def test_indicators():
    """測試指標計算"""
    print("\n=== 測試指標計算 ===")
    df = make_ohlcv(200, "up")
    result = add_all_indicators(df, verbose=True)

    expected_cols = ["rsi", "macd", "macd_signal", "macd_hist",
                     "bb_upper", "bb_middle", "bb_lower",
                     "ema_9", "ema_21", "ema_50",
                     "atr", "adx", "obv",
                     "stoch_rsi_k", "stoch_rsi_d"]
    for col in expected_cols:
        assert col in result.columns, f"Missing column: {col}"
    print(f"  columns: {len(result.columns)} (expected all {len(expected_cols)} indicators)")

    trend = get_trend_direction(result)
    print(f"  trend direction: {trend}")

    summary = get_indicator_summary(result)
    print(f"  indicator summary: {summary}")
    assert "rsi" in summary
    assert "trend" in summary
    print("  [PASS]")


def test_get_trend_direction_returns_lean_when_structure_is_transitional():
    df = make_ohlcv(60, "up")
    df = add_all_indicators(df)

    latest_idx = df.index[-1]
    df.loc[latest_idx, "ema_50"] = 100.0
    df.loc[latest_idx, "ema_21"] = 99.7
    df.loc[latest_idx, "ema_9"] = 101.0
    df.loc[latest_idx, "close"] = 101.2

    assert get_trend_direction(df) == "LEAN_BULLISH"


def test_divergence():
    """測試背離偵測"""
    print("\n=== 測試背離偵測 ===")
    df = make_ohlcv(200, "up")
    df = add_all_indicators(df)
    divergences = detect_all_divergences(df, lookback=60)
    print(f"  divergences found: {len(divergences)}")
    for d in divergences:
        print(f"    {d.type.value} on {d.indicator} (strength={d.strength:.2f})")

    highs = find_swing_highs(df["close"], order=5)
    lows = find_swing_lows(df["close"], order=5)
    print(f"  swing highs: {len(highs)}, swing lows: {len(lows)}")
    print("  [PASS]")


def test_fibonacci():
    """測試斐波那契"""
    print("\n=== 測試斐波那契 ===")
    df = make_ohlcv(200, "up")
    fib = calculate_fibonacci(df, lookback=100)
    assert fib is not None, "Fibonacci should not be None"
    print(f"  trend: {fib.trend}")
    print(f"  swing high: {fib.swing_high:.2f}, swing low: {fib.swing_low:.2f}")
    print(f"  retracement levels: {len(fib.retracement)}")
    for level, price in fib.retracement.items():
        print(f"    {level:.1%} = {price:.2f}")

    nearest = find_nearest_fib_levels(fib, df["close"].iloc[-1])
    print(f"  nearest support: {nearest['support']}")
    print(f"  nearest resistance: {nearest['resistance']}")

    summary = get_fib_summary(df)
    assert summary["available"] is True
    print("  [PASS]")


def test_candlestick():
    """測試 K 線型態"""
    print("\n=== 測試 K 線型態 ===")
    df = make_ohlcv(200, "up")
    patterns = detect_all_patterns(df, lookback=20)
    print(f"  patterns found: {len(patterns)}")
    for p in patterns:
        print(f"    {p.name} ({p.direction.value}) at idx={p.index}, conf={p.confidence:.2f}")

    signal = get_latest_pattern_signal(df)
    print(f"  latest signal: {signal}")
    print("  [PASS]")


def test_chop_detector():
    """測試絞肉機偵測"""
    print("\n=== 測試絞肉機偵測 ===")

    # 順暢趨勢
    df_trend = make_ohlcv(100, "up")
    df_trend = add_all_indicators(df_trend)
    chop_trend = detect_chop(df_trend)
    print(f"  trending market: is_chop={chop_trend.is_chop}, score={chop_trend.score}")

    # 震盪市場
    df_chop = make_ohlcv(100, "chop")
    df_chop = add_all_indicators(df_chop)
    chop_chop = detect_chop(df_chop)
    print(f"  choppy market: is_chop={chop_chop.is_chop}, score={chop_chop.score}")
    if chop_chop.reasons:
        for r in chop_chop.reasons:
            print(f"    reason: {r}")

    summary = get_chop_summary(df_chop)
    print(f"  chop summary: {summary}")
    print("  [PASS]")


def test_multi_timeframe():
    """測試多時間框架分析"""
    print("\n=== 測試多時間框架分析 ===")
    kline_data = {
        "15m": make_ohlcv(200, "up"),
        "1h": make_ohlcv(200, "up"),
        "4h": make_ohlcv(200, "up"),
    }
    result = analyze_multi_timeframe(kline_data)
    print(f"  alignment: {result.alignment.value}")
    print(f"  confidence: {result.confidence}")
    print(f"  recommended direction: {result.recommended_direction}")
    print(f"  details: {result.details}")

    summary = get_mtf_summary(kline_data)
    print(f"  summary: {summary}")
    print("  [PASS]")


def test_engine_integration():
    """測試 AnalysisEngine 整合"""
    print("\n=== 測試 AnalysisEngine 整合 ===")
    engine = AnalysisEngine()

    df = make_ohlcv(200, "up")
    single = engine.analyze_single("BTCUSDT", "15m", df)
    print(f"  single TF: indicators={bool(single.indicators)}, "
          f"divergences={len(single.divergences)}, "
          f"patterns={len(single.candle_patterns)}")

    kline_data = {
        "15m": make_ohlcv(200, "up"),
        "1h": make_ohlcv(200, "up"),
        "4h": make_ohlcv(200, "up"),
    }
    full = engine.analyze_full("BTCUSDT", kline_data)
    print(f"  full analysis: {len(full.single_tf_results)} timeframes")
    print(f"  MTF alignment: {full.mtf.alignment.value if full.mtf else 'N/A'}")
    print(f"  HTF RSI confirmed: {full.htf_rsi_confirmed}")

    snapshot = engine.get_analysis_snapshot(full)
    print(f"  snapshot keys: {list(snapshot.keys())}")
    assert "indicators" in snapshot
    assert "divergences" in snapshot
    assert "fibonacci" in snapshot
    assert "candle_pattern" in snapshot
    assert "chop" in snapshot
    assert "mtf" in snapshot
    print("  [PASS]")


def main():
    print("=" * 60)
    print("TradingBrain Phase 3 - 技術分析引擎測試")
    print("=" * 60)

    test_indicators()
    test_divergence()
    test_fibonacci()
    test_candlestick()
    test_chop_detector()
    test_multi_timeframe()
    test_engine_integration()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    main()
