"""Tests for Phase 2 breakout retest state machine."""

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


def _make_primary_result() -> SimpleNamespace:
    df = pd.DataFrame(
        [
            {
                "open_time": pd.Timestamp("2026-03-14 10:15:00"),
                "open": 100.0,
                "high": 101.2,
                "low": 99.8,
                "close": 101.0,
                "bb_upper": 100.5,
                "bb_lower": 98.5,
                "atr": 1.8,
            }
        ]
    )
    return SimpleNamespace(
        symbol="BTCUSDT",
        df_enriched=df,
        indicators={"atr": 1.8},
    )


def _make_one_min_result(
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
    ema9: float,
) -> SimpleNamespace:
    df = pd.DataFrame(
        [
            {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100.0,
                "ema_9": ema9,
            }
        ]
    )
    return SimpleNamespace(df_enriched=df)


async def _queue_breakout_pending_entry() -> None:
    brain = TradingBrain()
    brain.db = MagicMock()
    signal = TradeSignal(
        symbol="BTCUSDT",
        timeframe="15m",
        signal_type="LONG",
        strength=0.72,
        strategy_name="breakout",
        indicators={},
        reason="test breakout",
    )

    await brain._queue_pending_entries([signal], _make_primary_result(), "{}")

    pending = brain._pending_entries["BTCUSDT"][0]
    assert pending.breakout_price == 100.5
    assert pending.expire_bars == brain.BREAKOUT_RETEST_EXPIRE_BARS
    assert pending.signal_strength == signal.strength
    assert pending.retest_zone_low < pending.breakout_price < pending.retest_zone_high

    (log_payload,) = brain.db.insert_analysis_log.call_args[0]
    assert log_payload["final_action"] == "BREAKOUT_PENDING"


def test_queue_breakout_pending_entry():
    asyncio.run(_queue_breakout_pending_entry())


def test_breakout_retest_confirmed_same_bar():
    brain = TradingBrain()
    brain.db = MagicMock()
    pending = PendingEntry(
        signal=TradeSignal(
            symbol="BTCUSDT",
            timeframe="15m",
            signal_type="LONG",
            strength=0.8,
            strategy_name="breakout",
            indicators={},
            reason="breakout setup",
        ),
        market_snapshot_json="{}",
        setup_time=0.0,
        expires_at=9999999999.0,
        trigger_high=101.2,
        trigger_low=99.8,
        trigger_close=101.0,
        atr=1.8,
        structure_df=None,
        breakout_price=100.5,
        breakout_bar_time="2026-03-14T10:15:00",
        expire_bars=3,
        signal_strength=0.8,
        retest_zone_low=100.15,
        retest_zone_high=100.85,
    )

    one_min_result = _make_one_min_result(
        open_price=100.4,
        high=100.9,
        low=100.3,
        close=100.8,
        ema9=100.2,
    )

    next_pending, trigger_check, confirmed_signal = brain._process_breakout_retest_entry(
        pending,
        one_min_result,
    )

    assert next_pending is None
    assert trigger_check.triggered is True
    assert confirmed_signal is not None
    assert confirmed_signal.strategy_name == "breakout_retest"

    logged_actions = [
        call.args[0]["final_action"] for call in brain.db.insert_analysis_log.call_args_list
    ]
    assert logged_actions == ["BREAKOUT_RETEST_HIT", "BREAKOUT_CONFIRMED"]


def test_breakout_retest_expires_after_three_bars():
    brain = TradingBrain()
    brain.db = MagicMock()
    pending = PendingEntry(
        signal=TradeSignal(
            symbol="BTCUSDT",
            timeframe="15m",
            signal_type="LONG",
            strength=0.8,
            strategy_name="breakout",
            indicators={},
            reason="breakout setup",
        ),
        market_snapshot_json="{}",
        setup_time=0.0,
        expires_at=9999999999.0,
        trigger_high=101.2,
        trigger_low=99.8,
        trigger_close=101.0,
        atr=1.8,
        structure_df=None,
        breakout_price=100.5,
        breakout_bar_time="2026-03-14T10:15:00",
        expire_bars=3,
        signal_strength=0.8,
        retest_zone_low=100.15,
        retest_zone_high=100.85,
        bars_waited=2,
    )

    one_min_result = _make_one_min_result(
        open_price=101.1,
        high=101.4,
        low=101.0,
        close=101.2,
        ema9=100.9,
    )

    next_pending, trigger_check, confirmed_signal = brain._process_breakout_retest_entry(
        pending,
        one_min_result,
    )

    assert next_pending is None
    assert trigger_check.triggered is False
    assert trigger_check.reason == "breakout_retest_expired"
    assert confirmed_signal is None

    (log_payload,) = brain.db.insert_analysis_log.call_args[0]
    assert log_payload["final_action"] == "BREAKOUT_EXPIRED"
