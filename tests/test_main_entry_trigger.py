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


def test_entry_triggered_trend_following_c_grade_requires_all_supports():
    brain = TradingBrain.__new__(TradingBrain)
    pending = PendingEntry(
        signal=TradeSignal(
            symbol="BTCUSDT",
            timeframe="15m",
            signal_type="LONG",
            strength=0.3,
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
        signal_strength=0.3,
    )
    result = brain._entry_triggered(
        pending,
        _one_min_result(close=100.4, open=100.1, ema_9=100.2, rsi=49.0),
    )

    assert result.triggered is False


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


def test_entry_triggered_mean_reversion_c_grade_requires_both_supports():
    brain = TradingBrain.__new__(TradingBrain)
    pending = PendingEntry(
        signal=TradeSignal(
            symbol="BTCUSDT",
            timeframe="15m",
            signal_type="LONG",
            strength=0.2,
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
        signal_strength=0.2,
    )
    result = brain._entry_triggered(
        pending,
        _one_min_result(close=100.3, open=100.4, ema_9=100.1),
    )

    assert result.triggered is False


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


def test_breakout_retest_a_grade_can_confirm_inside_zone_without_breakout_close():
    brain = TradingBrain()
    brain.db = MagicMock()
    pending = PendingEntry(
        signal=TradeSignal(
            symbol="BTCUSDT",
            timeframe="15m",
            signal_type="LONG",
            strength=0.75,
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
        signal_strength=0.75,
        retest_zone_low=100.15,
        retest_zone_high=100.85,
        state="retest_zone",
    )

    one_min_result = _one_min_result(
        close=100.4,
        open=100.1,
        high=100.7,
        low=100.2,
        ema_9=100.2,
    )

    next_pending, trigger_check, confirmed_signal = brain._process_breakout_retest_entry(
        pending,
        one_min_result,
    )

    assert next_pending is None
    assert trigger_check.triggered is True
    assert confirmed_signal is not None
    assert confirmed_signal.strategy_name == "breakout_retest"


def test_run_risk_and_execute_blocks_when_mtf_recheck_flips():
    async def _run():
        brain = TradingBrain.__new__(TradingBrain)
        brain.db = MagicMock()
        brain.binance_client = None
        brain.risk_manager = MagicMock()
        brain._quick_mtf_direction_check = MagicMock(return_value="SHORT")

        sig = TradeSignal(
            symbol="BTCUSDT",
            timeframe="15m",
            signal_type="LONG",
            strength=0.8,
            strategy_name="trend_following",
        )

        result = await brain._run_risk_and_execute(sig, 100.0, 2.0, "{}")
        assert result is None
        brain.risk_manager.evaluate.assert_not_called()
        (log_payload,) = brain.db.insert_analysis_log.call_args[0]
        assert log_payload["final_action"] == "MTF_RECHECK_BLOCK"

    asyncio.run(_run())
