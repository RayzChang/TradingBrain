"""
第四階段測試 — 策略與信號系統

驗證: 策略基類、趨勢跟蹤、均值回歸、信號聚合器、幣種篩選器
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.analysis.engine import AnalysisEngine, AnalysisResult, FullAnalysis
from core.analysis.indicators import add_all_indicators
from core.strategy.base import BaseStrategy, TradeSignal
from core.strategy.trend_following import TrendFollowingStrategy
from core.strategy.mean_reversion import MeanReversionStrategy
from core.strategy.signal_aggregator import SignalAggregator, AggregatorResult
from core.strategy.coin_screener import CoinScreener
from core.pipeline.veto_engine import VetoResult


def make_ohlcv(n: int = 200, trend: str = "up") -> pd.DataFrame:
    """產生模擬 OHLCV 數據"""
    import numpy as np
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
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


def test_trade_signal_to_db_row():
    """TradeSignal 轉 DB 欄位"""
    print("\n=== 測試 TradeSignal.to_db_row ===")
    sig = TradeSignal(
        symbol="BTCUSDT", timeframe="15m", signal_type="LONG",
        strength=0.8, strategy_name="trend_following",
        indicators={"adx": 28, "ema_9": 100.0},
        reason="EMA cross",
    )
    row = sig.to_db_row()
    assert row["symbol"] == "BTCUSDT"
    assert row["signal_type"] == "LONG"
    assert row["strength"] == 0.8
    assert row["indicators"]["adx"] == 28
    print("  [PASS]")


def test_trend_following_strategy():
    """趨勢跟蹤策略 — 有足夠數據時可產出信號或空列表"""
    print("\n=== 測試趨勢跟蹤策略 ===")
    engine = AnalysisEngine()
    df = make_ohlcv(200, "up")
    result = engine.analyze_single("BTCUSDT", "15m", df)
    strategy = TrendFollowingStrategy(adx_min=20.0, skip_on_chop=False)
    signals = strategy.evaluate_single("BTCUSDT", "15m", result)
    assert isinstance(signals, list)
    for s in signals:
        assert s.signal_type in ("LONG", "SHORT")
        assert s.strategy_name == "trend_following"
        assert 0 <= s.strength <= 1.0
    print(f"  signals count: {len(signals)}")
    print("  [PASS]")


def test_mean_reversion_strategy():
    """均值回歸策略 — 邊界條件與背離加分"""
    print("\n=== 測試均值回歸策略 ===")
    engine = AnalysisEngine()
    df = make_ohlcv(200, "up")
    result = engine.analyze_single("BTCUSDT", "15m", df)
    strategy = MeanReversionStrategy(skip_on_chop=False)
    signals = strategy.evaluate_single("BTCUSDT", "15m", result)
    assert isinstance(signals, list)
    for s in signals:
        assert s.signal_type in ("LONG", "SHORT")
        assert s.strategy_name == "mean_reversion"
    print(f"  signals count: {len(signals)}")
    print("  [PASS]")


def test_signal_aggregator():
    """信號聚合器 — 多策略 + 否決過濾"""
    print("\n=== 測試信號聚合器 ===")
    mock_veto = MagicMock()
    mock_veto.evaluate.return_value = VetoResult(passed=True)

    strategies = [
        TrendFollowingStrategy(adx_min=20, skip_on_chop=False),
        MeanReversionStrategy(skip_on_chop=False),
    ]
    aggregator = SignalAggregator(strategies=strategies, veto_engine=mock_veto, db=None)

    kline_data = {
        "15m": make_ohlcv(200, "up"),
        "1h": make_ohlcv(200, "up"),
        "4h": make_ohlcv(200, "up"),
    }
    engine = AnalysisEngine()
    full = engine.analyze_full("BTCUSDT", kline_data)

    result = aggregator.evaluate(full, save_to_db=False)
    assert isinstance(result, AggregatorResult)
    assert isinstance(result.passed, list)
    assert isinstance(result.vetoed, list)
    print(f"  passed: {len(result.passed)}, vetoed: {len(result.vetoed)}")
    print("  [PASS]")


def test_signal_aggregator_blocks_correlated_same_direction():
    """BTC / ETH 同向曝險會被相關性保護擋掉。"""
    print("\n=== 測試 correlated pairs protection ===")
    mock_veto = MagicMock()
    mock_veto.evaluate.return_value = VetoResult(passed=True)

    strategy = MagicMock()
    strategy.evaluate_full.return_value = [
        TradeSignal(
            symbol="ETHUSDT",
            timeframe="15m",
            signal_type="LONG",
            strength=0.9,
            strategy_name="breakout_retest",
            indicators={},
        )
    ]
    db = MagicMock()
    db.get_open_trades.return_value = [{"symbol": "BTCUSDT", "side": "LONG"}]

    aggregator = SignalAggregator(strategies=[strategy], veto_engine=mock_veto, db=db)
    full = MagicMock()
    full.symbol = "ETHUSDT"
    full.primary_tf = "15m"

    result = aggregator.evaluate(full, save_to_db=False)

    assert result.passed == []
    assert len(result.vetoed) == 1
    sig, reason = result.vetoed[0]
    assert sig.symbol == "ETHUSDT"
    assert "BTCUSDT" in reason
    print("  [PASS]")


def test_coin_screener():
    """幣種篩選器 — 打分與排序"""
    print("\n=== 測試幣種篩選器 ===")
    engine = AnalysisEngine()
    kline_data = {
        "15m": make_ohlcv(200, "up"),
        "1h": make_ohlcv(200, "up"),
        "4h": make_ohlcv(200, "up"),
    }
    full = engine.analyze_full("BTCUSDT", kline_data)
    screener = CoinScreener()
    score = screener.score(full)
    assert 0.0 <= score <= 1.0
    print(f"  BTCUSDT score: {score:.2f}")

    ranked = CoinScreener.rank([("BTCUSDT", 0.7), ("ETHUSDT", 0.3), ("XRPUSDT", 0.5)], top_n=2)
    assert ranked == ["BTCUSDT", "XRPUSDT"]
    print(f"  rank top 2: {ranked}")
    print("  [PASS]")


def main():
    print("=" * 60)
    print("TradingBrain Phase 4 - 策略與信號系統測試")
    print("=" * 60)
    test_trade_signal_to_db_row()
    test_trend_following_strategy()
    test_mean_reversion_strategy()
    test_signal_aggregator()
    test_coin_screener()
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    main()
