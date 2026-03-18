from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.strategy.base import TradeSignal
from main import PendingEntry, TradingBrain


def _one_min_result(**kwargs):
    row = {
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 1000.0,
        "ema_9": 100.2,
        "rsi": 52.0,
    }
    row.update(kwargs)
    df = pd.DataFrame([row] * 30)
    return SimpleNamespace(df_enriched=df)


def test_entry_triggered_trend_following_long_uses_core_plus_two_of_three():
    brain = TradingBrain.__new__(TradingBrain)
    pending = PendingEntry(
        signal=TradeSignal(
            symbol="BTCUSDT",
            timeframe="15m",
            signal_type="LONG",
            strength=0.8,
            strategy_name="trend_following",
        ),
        market_snapshot_json=None,
        setup_time=0.0,
        expires_at=0.0,
        trigger_high=101.0,
        trigger_low=99.0,
        trigger_close=100.0,
        atr=1.0,
        structure_df=None,
    )
    result = brain._entry_triggered(
        pending,
        _one_min_result(close=100.4, open=100.1, ema_9=100.2, rsi=49.0),
    )

    assert result.triggered is True


def test_entry_triggered_mean_reversion_long_uses_core_plus_one_of_two():
    brain = TradingBrain.__new__(TradingBrain)
    pending = PendingEntry(
        signal=TradeSignal(
            symbol="BTCUSDT",
            timeframe="15m",
            signal_type="LONG",
            strength=0.8,
            strategy_name="mean_reversion",
        ),
        market_snapshot_json=None,
        setup_time=0.0,
        expires_at=0.0,
        trigger_high=101.0,
        trigger_low=99.0,
        trigger_close=100.0,
        atr=1.0,
        structure_df=None,
    )
    result = brain._entry_triggered(
        pending,
        _one_min_result(close=100.3, open=100.4, ema_9=100.1),
    )

    assert result.triggered is True


def test_queue_pending_entries_extends_non_breakout_window_to_45_minutes():
    brain = TradingBrain.__new__(TradingBrain)
    brain._pending_entries = {}
    brain.db = MagicMock()

    signal = TradeSignal(
        symbol="BTCUSDT",
        timeframe="15m",
        signal_type="LONG",
        strength=0.8,
        strategy_name="trend_following",
        indicators={},
    )
    primary_df = pd.DataFrame(
        [
            {"high": 101.0, "low": 99.0, "close": 100.0, "open_time": pd.Timestamp("2026-03-18 00:00:00")},
            {"high": 102.0, "low": 100.0, "close": 101.0, "open_time": pd.Timestamp("2026-03-18 00:15:00")},
        ]
    )
    primary = SimpleNamespace(
        symbol="BTCUSDT",
        df_enriched=primary_df,
        indicators={"atr": 1.0},
    )

    asyncio.run(brain._queue_pending_entries([signal], primary, {"regime": "trending"}))

    pending = brain._pending_entries["BTCUSDT"][0]
    assert pending.expires_at - pending.setup_time == 45 * 60
