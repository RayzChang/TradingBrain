"""
第七階段測試 — 回測引擎

驗證：載入數據、跑回測、報告結構
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.backtest.engine import BacktestEngine, BacktestResult
from core.backtest.report import get_report_dict, format_report


def make_ohlcv(bars: int = 300) -> pd.DataFrame:
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=bars, freq="15min")
    base = 100 + np.cumsum(np.random.randn(bars) * 0.3)
    noise = np.random.randn(bars) * 0.5
    high = base + np.abs(noise) + np.random.rand(bars) * 0.5
    low = base - np.abs(noise) - np.random.rand(bars) * 0.5
    close = base + noise * 0.5
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.random.rand(bars) * 1e6 + 1e5
    return pd.DataFrame({
        "open_time": dates,
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


def test_backtest_engine():
    print("\n=== 回測引擎 ===")
    engine = BacktestEngine(symbol="BTCUSDT", timeframe="15m", initial_balance=300)
    df = make_ohlcv(350)
    result = engine.run(df)
    assert isinstance(result, BacktestResult)
    assert result.initial_balance == 300
    assert len(result.equity_curve) > 0
    assert result.n_trades >= 0
    d = get_report_dict(result)
    assert "total_return_pct" in d
    assert "max_drawdown_pct" in d
    assert "win_rate" in d
    text = format_report(result)
    assert "回測報告" in text
    assert "總報酬率" in text
    print(f"  交易次數: {result.n_trades}, 總報酬: {result.total_return_pct:.2f}%, 最大回撤: {result.max_drawdown_pct:.2f}%")
    print("  [PASS]")


def main():
    print("=" * 60)
    print("TradingBrain Phase 7 - 回測系統測試")
    print("=" * 60)
    test_backtest_engine()
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    main()
