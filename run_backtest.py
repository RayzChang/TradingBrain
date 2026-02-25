"""
回測 CLI — 使用 Parquet 或內建模擬數據跑一次回測並印出報告

用法:
  python run_backtest.py
  python run_backtest.py --symbol BTCUSDT --tf 15m
  python run_backtest.py --days 90
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import KLINE_DATA_DIR
from core.backtest.engine import BacktestEngine
from core.backtest.report import format_report


def make_sample_ohlcv(bars: int = 500) -> pd.DataFrame:
    """產生模擬 K 線（無 Parquet 時使用）"""
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


def main() -> None:
    parser = argparse.ArgumentParser(description="TradingBrain 回測")
    parser.add_argument("--symbol", default="BTCUSDT", help="交易對")
    parser.add_argument("--tf", "--timeframe", dest="timeframe", default="15m", help="時間框架")
    parser.add_argument("--balance", type=float, default=300, help="初始資金 USDT")
    parser.add_argument("--days", type=int, default=0, help="若無 Parquet 則用模擬數據的 K 線數（0=用 Parquet 或 500 根模擬）")
    args = parser.parse_args()

    engine = BacktestEngine(
        symbol=args.symbol,
        timeframe=args.timeframe,
        initial_balance=args.balance,
        slippage_pct=0.001,
        fee_rate=0.0004,
    )

    path = KLINE_DATA_DIR / f"{args.symbol}_{args.timeframe}.parquet"
    if path.exists():
        df = engine.load_data(path)
        print(f"載入 Parquet: {path}，共 {len(df)} 根 K 線")
    else:
        bars = args.days * (24 * 60 // 15) if args.days else 500
        df = make_sample_ohlcv(bars)
        print(f"使用模擬數據: {len(df)} 根 K 線")
    if len(df) < 100:
        print("K 線不足 100 根，無法回測")
        sys.exit(1)

    result = engine.run(df)
    print(format_report(result))


if __name__ == "__main__":
    main()
